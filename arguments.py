import argparse
import os
import torch
import deepspeed
import json


def get_args():

    parser = argparse.ArgumentParser()
    parser = add_model_config_args(parser)
    parser = add_logging_config_args(parser)
    parser = add_data_config_args(parser)
    parser = add_transform_config_args(parser)
    parser = add_augment_config_args(parser)
    parser = add_training_config_args(parser)
    parser = add_validation_config_args(parser)

    parser.add_argument('--local_rank', type=int, help='local rank passed from distributed launcher')
    parser = deepspeed.add_config_arguments(parser)

    args = parser.parse_args()

    with open(args.deepspeed_config) as f:
        deepspeed_args = json.load(f)

    for k in deepspeed_args.keys():
        setattr(args, k, deepspeed_args.get(k))

    return args


def add_model_config_args(parser):
    group = parser.add_argument_group('model', 'Model type and settings')

    group.add_argument('--model_name', type=str, default='i3d_bert', help='Used for model selection and logging',
                       choices=['ccnn', 'i3d', 'i3d_bert'])
    group.add_argument('--data_type', type=str, default='multi-stream', help='The type of input data to the model',
                       choices=['img', 'flow', 'multi-stream'])
    group.add_argument('--n_inputs', type=int, default=8, help='The number of inputs to the model.')
    group.add_argument('--n_outputs', type=int, default=1, help='The number of outputs from the model.')
    group.add_argument('--pre_n_outputs', type=int, default=400, help='The number of outputs from the model used as '
                                                                      'pre-training. If it differs from n_outputs, '
                                                                      'final layer will be replaced')
    group.add_argument('--continue_training', type=bool, default=False, help='When enabled, training is resumed from a '
                                                                             'multistream model rather than multiple '
                                                                             'single stream models')
    group.add_argument('--pre_trained_checkpoint', type=str, help='checkpoint used to initialize a model')
    group.add_argument('--pre_trained_i3d_img', type=str, help='Image checkpoint used in conjuction with a flow '
                                                                      'checkpoint to initialize a multistream model')
    group.add_argument('--pre_trained_i3d_flow', type=str, help='Image checkpoint used in conjuction with a flow '
                                                                      'checkpoint to initialize a multistream model')
    group.add_argument('--shared_weights', type=bool, default=True,
                       help='Boolean flag that controls if weights are shared over all inputs of the same type '
                            '(img/flow) or separate for each input')
    group.add_argument('--n_input_channels_img', type=int, default=1,
                       help='Number of input channels for image data type')
    group.add_argument('--n_input_channels_flow', type=int, default=2,
                       help='Number of input channels for flow data type')

    return parser


def add_logging_config_args(parser):
    group = parser.add_argument_group('logging', "Settings for online logging to Neptune")

    group.add_argument('--logging_enabled', type=bool, default=True, help='Enables logging to Neptune')
    group.add_argument('--project_name', type=str, help='Name of account and project in Neptune in format name/project')

    return parser


def add_data_config_args(parser):
    group = parser.add_argument_group('data', 'Settings for data, both reading from disk and loading into model')

    group.add_argument('--data_in_mem', type=bool, default=False, help='When enabled, a new Dataset will load all data '
                                                                       'from disk into RAM on creation.')
    group.add_argument('--preprocessed_data_on_disk', type=bool, default=True, help='When enabled, a new Dataset will '
                                                                                    'apply all transforms on its data '
                                                                                    'and then write the processed data '
                                                                                    'to a temporary folder on disk. '
                                                                                    'Retreiving data will read from the'
                                                                                    ' temp folder instead of original '
                                                                                    'path or RAM.')
    group.add_argument('--only_use_complete_exams', type=bool, default=False, help='When enabled, only examinations with'
                                                                                   ' at least one view of each type is '
                                                                                   'considered. Otherwise, missing views'
                                                                                   ' are replaced by dummy data.')
    group.add_argument('--temp_folder_img', type=str, help='Path to where temporary image data generated by '
                                                           'preprocessed_data_on_disk should be saved.')
    group.add_argument('--temp_folder_flow', type=str, help='Path to where temporary flow data generated by '
                                                           'preprocessed_data_on_disk should be saved.')
    group.add_argument('--file_sep', type=str, default=';', help='Separator used when reading target files')
    group.add_argument('--train_targets', type=str, help='Path to target file for training data')
    group.add_argument('--val_targets', type=str, help='Path to target file for validation data')
    group.add_argument('--allowed_views', nargs='+', type=int, required=True, help='Identifiers to allowed view labels.'
                                                                                   'Example: --allowed_views 0 2 4')
    group.add_argument('--data_folder_img', type=str, required=True, help='Path to folder containing image data')
    group.add_argument('--data_folder_flow', type=str, required=True, help='Path to folder containing flow data')

    group.add_argument('--eval_batch_size', type=int, default=16, help='Batch size for validation data loader')
    #Note that --train_batch_size is set inside deepspeed config
    group.add_argument('--n_workers', type=int, default=20, help='Number of workers used in DataLoader')
    group.add_argument('--drop_last', type=bool, default=True, help='When enabled, drops the last batch from DataLoader '
                                                                    'if not full-sized')
    group.add_argument('--weighted_sampler', type=bool, default=True, help='When enabled, sampling from DataLoader is '
                                                                           'weighted by the each samples loss relative '
                                                                           'to its batch mean')
    group.add_argument('--pin_memory', type=bool, default=True, help='When enabled sets pin_memory in all Dataloaders')

    return parser


def add_transform_config_args(parser):
    group = parser.add_argument_group('transforms', 'Data transform settings')

    group.add_argument('--org_height', type=int, default=484, help='Original frame height')
    group.add_argument('--org_width', type=int, default=636, help='Original frame width')
    group.add_argument('--grayscale', type=bool, default=False, help='When enabled, converts inputs to grayscale')
    group.add_argument('--normalize_input', type=bool, default=True, help='When enabled, normalizes input data into the'
                                                                          ' range -1 to 1')
    group.add_argument('--rescale_fps', type=bool, default=False, help='Rescale each video to the same fps')
    group.add_argument('--target_fps', type=int, default=15, help='The fps value used for fps rescaling')
    group.add_argument('--rescale_fphb', type=bool, default=True, help='Rescale each video to the same frames per heartbeat')
    group.add_argument('--target_fphb', type=int, default=15, help='The frames per heartbeat value used for fphb rescaling')
    group.add_argument('--resize_frames', type=bool, default=True, help='When enabled, each frame is resized into a new size')
    group.add_argument('--target_height', type=int, default=97, help='The height used as target for frame resizing')
    group.add_argument('--target_width', type=int, default=127, help='The width used as target for frame resizing')
    group.add_argument('--crop_length', type=bool, default=True, help='When enabled, video length is cropped if video '
                                                                       'length is longer than target length')
    group.add_argument('--loop_length', type=bool, default=True, help='When enabled, video is looped if video length is '
                                                                      'shorter than target length')
    group.add_argument('--target_length', type=int, default=15, help='The target length used for cropping and loooping.')

    return parser


def add_augment_config_args(parser):
    group = parser.add_argument_group('augment', 'Data augmentation settings')

    group.add_argument('--gaussian_noise', type=bool, default=False, help='Enables Gaussian noise.')
    group.add_argument('--gn_var', type=float, default=0.01, help='Gaussian noise variance.')
    group.add_argument('--speckle', type=bool, default=False, help='Enables Speckle noise.')
    group.add_argument('--speckle_var', type=float, default=0.01, help='Speckle variance.')
    group.add_argument('--salt_and_pepper', type=bool, default=False, help='Enables salt and pepper noise.')
    group.add_argument('--salt_and_pepper_amount', type=float, default=0.01, help='Salt and pepper amount.')
    group.add_argument('--shift_v', type=bool, default=False, help='Enables random vertical shift.')
    group.add_argument('--shift_v_std_dev_pxl', type=int, default=10, help='Standard deviation for vertical shift.')
    group.add_argument('--shift_h', type=bool, default=False, help='Enables random horizontal shift.')
    group.add_argument('--shift_h_std_dev_pxl', type=int, default=10, help='Standard deviation for horizontal shift.')
    group.add_argument('--rotate', type=bool, default=False, help='Enables random rotation')
    group.add_argument('--rotate_std_dev_degrees', type=int, default=15, help='Standard deviation for rotation.')
    group.add_argument('--local_blackout', type=bool, default=False, help='Enables random local blackout.')
    group.add_argument('--blackout_h_std_dev', type=int, default=10,
                       help='Height standard deviation for local blackout.')
    group.add_argument('--blackout_w_std_dev', type=int, default=10,
                       help='Width standard deviation for local blackout.')
    group.add_argument('--local_intensity', type=bool, default=False, help='Enables random local intensity shift.')
    group.add_argument('--intensity_h_std_dev', type=int, default=10,
                       help='Height standard deviation for local intensity.')
    group.add_argument('--intensity_w_std_dev', type=int, default=10,
                       help='Width standard deviation for local intensity.')
    group.add_argument('--intensity_var', type=float, default=0.01, help='Local intensity shift variance.')


    return parser


def add_training_config_args(parser):
    group = parser.add_argument_group('training', 'Training settings')

    group.add_argument('--cuddn_auto_tuner', type=bool, default=True, help='Enables the CUDDN benchmark in PyTorch')
    group.add_argument('--anomaly_detection', type=bool, default=False, help='Enables PyTorch anomaly detection')
    group.add_argument('--epochs', type=int, default=500, help='Number of training epochs')
    group.add_argument('--checkpointing_enabled', type=bool, default=True, help='When enabled, the best model is '
                                                                                'continuously saved to disk as a '
                                                                                'checkpoint during training')
    group.add_argument('--checkpoint_save_path', type=str, default='checkpoints/', help='Folder where the checkpoint'
                                                                                        ' should be saved')
    group.add_argument('--freeze_lower', type=bool, default=False, help='When enabled, all layers except last are frozen')

    return parser


def add_validation_config_args(parser):
    group = parser.add_argument_group('validation', 'Validation settings')

    group.add_argument('--all_view_combinations', type=bool, default=True, help='When enabled, all possible combinations'
                                                                                ' of allowed views are considered during'
                                                                                ' validation and results for each '
                                                                                'combination is weighted by the ratio of'
                                                                                ' combinations in each examination')
    return parser

args = get_args()