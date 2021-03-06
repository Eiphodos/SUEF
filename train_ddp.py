import neptune.new as neptune
import hydra
import torch
import torch.multiprocessing as mp
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
import logging
from copy import copy
from omegaconf import DictConfig
import os
from utils.utils import create_and_load_model, create_data_sets, create_data_loaders, update_cfg, create_train_loader, log_train_metrics, log_val_metrics, save_checkpoint
from utils.ddp_utils import prepare_ddp, init_distributed_mode, is_master, cleanup, is_dist_avail_and_initialized
from Trainers import DDPTrainer
from Validators import DDPValidator

logging.basicConfig(level=logging.INFO)
logging.getLogger('numexpr').setLevel(logging.WARNING)


@hydra.main(config_path="cfg", config_name="config")
def main(cfg: DictConfig) -> None:

    assert cfg.model.name in ['ccnn', 'resnext', 'i3d', 'i3d_bert', 'i3d_bert_2stream']
    assert cfg.data.type in ['img', 'flow', 'multi-stream']

    train_data_set, val_data_set = create_data_sets(cfg)

    prepare_ddp(cfg)
    mp.set_start_method('spawn')
    processes = []
    for rank in range(cfg.world_size):
        process_config = copy(cfg)
        update_cfg(process_config, key='rank', val=rank)
        p = mp.Process(target=train_and_val, args=(process_config, train_data_set, val_data_set))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()


def train_and_val(cfg, train_data_set, val_data_set):
    ### INITIALIZE DDP ###
    if cfg.performance.ddp:
        init_distributed_mode(cfg)

    ### SETUP MODEL ###
    # If distributed, the specific cuda device is configured in init_distributed_mode
    device = torch.device(cfg.performance.device)
    model, tags = create_and_load_model(cfg)
    model.to(device)
    model_no_ddp = model
    if cfg.performance.ddp:
        model = DDP(model, device_ids=[cfg.rank], find_unused_parameters=False)
        model_no_ddp = model.module

    # CUDNN Auto-tuner. Use True when input size and model is static
    torch.backends.cudnn.benchmark = cfg.performance.cuddn_auto_tuner

    ### SETUP LOGGING AND CHECKPOINTING ###
    if is_master():
        experiment = None
        if cfg.logging.logging_enabled:
            experiment_params = {**dict(cfg.data_loader), **dict(cfg.transforms), **dict(cfg.augmentations),
                                 **dict(cfg.performance), **dict(cfg.training), **dict(cfg.optimizer),
                                 **dict(cfg.model),
                                 **dict(cfg.evaluation), 'target_file': cfg.data.train_targets,
                                 'data_stream': cfg.data.type, 'view': cfg.data.name,
                                 'train_dataset_size': len(train_data_set),
                                 'val_dataset_size': len(val_data_set)}
            experiment = neptune.init(project=cfg.logging.project_name, name=cfg.logging.experiment_name, tags=tags)
            experiment['parameters'] = experiment_params

        if not os.path.exists(cfg.training.checkpoint_save_path):
            os.makedirs(cfg.training.checkpoint_save_path)

    ### SETUP CRITERION AND OPTIMIZER
    # Set loss criterion
    criterion = torch.nn.MSELoss(reduction='none')
    # Set optimizer
    optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, model_no_ddp.parameters()),
                                  lr=cfg.optimizer.learning_rate, weight_decay=cfg.optimizer.weight_decay)
    if cfg.optimizer.use_scheduler:
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=cfg.optimizer.s_patience, factor=cfg.optimizer.s_factor)

    ### SETUP DATALOADERS ###
    if is_master():
        train_data_loader, val_data_loader = create_data_loaders(cfg, train_data_set, val_data_set)
    else:
        train_data_loader = create_train_loader(cfg, train_data_set)

    ### SETUP TRAINER AND VALIDATOR ###
    validator = DDPValidator(criterion, device, cfg)
    trainer = DDPTrainer(criterion, device, cfg)

    max_val_r2 = None

    ### TRAINING START ###
    for i in range(cfg.training.epochs):
        # TRAIN EPOCH
        train_loss, train_r2 = trainer.train_epoch(model, train_data_loader, optimizer, i)

        # TRAIN LOGGING
        if is_master():
            if cfg.logging.logging_enabled:
                log_train_metrics(experiment, train_loss.avg[0], train_r2.avg[0], optimizer.param_groups[0]['lr'])

        # RUN VALIDATION
        if is_master() and i % 10 == 0:
            val_loss_mean, val_r2 = validator.validate(model, val_data_loader, i)


            # VAL LOGGING/CHECKPOINTING
            if cfg.logging.logging_enabled:
                experiment_id = experiment["sys/id"].fetch()
                checkpoint_name = cfg.training.checkpoint_save_path + cfg.model.name + '_' + cfg.data.type + '_' \
                                  + cfg.data.name + '_exp_' + experiment_id + '.pth'
                log_val_metrics(experiment, val_loss_mean, val_r2, max_val_r2)
            else:
                checkpoint_name = cfg.training.checkpoint_save_path + cfg.model.name + '_' + cfg.data.type + '_' \
                                  + cfg.data.name + '_test' + '.pth'
            if max_val_r2 is None or val_r2 > max_val_r2:
                max_val_r2 = val_r2
                if cfg.training.checkpointing_enabled:
                    save_checkpoint(checkpoint_name, model_no_ddp, optimizer)


        # END OF EPOCH
        if is_dist_avail_and_initialized():
            dist.barrier()
        if cfg.optimizer.use_scheduler:
            if is_master():
                val_loss_tensor = torch.tensor(val_loss_mean, device=device)
            else:
                val_loss_tensor = torch.tensor(0, dtype=torch.float64, device=device)
            dist.broadcast(val_loss_tensor, src=0)
            scheduler.step(val_loss_tensor)
    cleanup()


if __name__ == "__main__":
    main()
