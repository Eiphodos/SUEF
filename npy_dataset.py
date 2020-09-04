import torch
import numpy as np
import pandas as pd
import cnn_data_aug
import os


class NPYDataset(torch.utils.data.Dataset):
    '''
    Custom dataset for loading files in the format generated by the preprocessing step.
    Image files expected as .npy files with a user id in the start of the file name.
    Targets/labels expected as a csv file.
    '''
    def __init__(self, image_path, target_file, target_file_sep, uid_len, transform_flags={}):
        '''
        Initialize a new CustomDataset.
        :param image_path: The path to the image files in .npy format (Str)
        :param target_file: The path to the csv file containing the targets (Str)
        :param target_file_sep: The separator for reading the csv file (Str)
        :param uid_len: The length of the user id at the start of the filenames.
        '''
        super(NPYDataset).__init__()

        self.targets = pd.read_csv(os.path.abspath(target_file), sep=target_file_sep)
        self.img_dict = self.load_filenames( os.path.abspath(image_path), uid_len)
        self.transform = cnn_data_aug.DataAugmentations(transform_flags)


    def __len__(self):
        return len(self.targets)

    def __getitem__(self, index):
        uid = self.targets.iloc[index]['us_id']
        target = self.targets.iloc[index]['target']
        f_path = self.img_dict[uid]
        print(f_path)
        img = np.load(os.path.abspath(f_path), allow_pickle=True)

        if self.transform:
            img = self.transform(img)

        return img, target

    @staticmethod
    def load_filenames(path, uid_len):
        '''
        Returns a dictionary of user_id:filepath
        It is assumed that the first uid_len characters in the filename is the user_id
        :param path: root directory containing all files (Str)
        :param uid_len: length of user_id in the filename (Int)
        :return: dictionary of userids and paths (Dict)
        '''
        files = {}
        for dirName, _, fileList in os.walk(path):
            for filename in fileList:
                files[filename[0:uid_len]] = os.path.join(dirName, filename)
        return files
