import numpy as np
from skimage.util import random_noise, img_as_float32, crop
from skimage.color import rgb2gray
from skimage.transform import resize, rescale, rotate
from random import choice, randint
import math
import time
from omegaconf import OmegaConf, DictConfig
import cv2


class DataAugmentations:
    def __init__(self, transforms, augmentations):
        '''
        Class for all transforms and augmentations to be applied.
        Holds configurations on what to apply and methods for
        applying them.
        :param transforms: OmegaConf object for transform settings/flags
        :param augmentations:  OmegaConf object for augmentation settings/flags
        '''
        super(DataAugmentations).__init__()
        
        self.transforms = transforms
        self.augmentations = augmentations
        self.debug = False

        if self.transforms.normalize_input:
            self.black_val = -1.0
            self.white_val = 1.0
        else:
            self.black_val = 0.0
            self.white_val = 255.0

    def transform_values(self, img):
        '''
        Transform values of an input image.
        :param img: Multidimensional input image with values in range 0-255.
        :return: The transformed input.
        '''
        time_start = time.time()
        # Pixel values expected to be in range 0-255
        if self.transforms.normalize_input:
            img = self.t_normalize_signed(img)
        if self.debug:
            time_ni = time.time()
            time_ni_diff = time_ni - time_start
            print("Normalized input. Time to process: {}".format(time_ni_diff))

        # Add some kind of noise to the image
        if self.augmentations.gaussian_noise:
            img = self.t_gaussian_noise(img)
        if self.debug:
            time_gn = time.time()
            time_gn_diff = time_gn - time_ni
            print("Added gaussian noise. Time to process: {}".format(time_gn_diff))
        if self.augmentations.speckle:
            img = self.t_speckle(img)
        if self.debug:
            time_spk = time.time()
            time_spk_diff = time_spk - time_gn
            print("Added speckle. Time to process: {}".format(time_spk_diff))
        if self.augmentations.salt_and_pepper:
            img = self.t_salt_and_pepper(img)
        if self.debug:
            time_sp = time.time()
            time_sp_diff = time_sp - time_spk
            print("Added Salt and Pepper. Time to process: {}".format(time_sp_diff))

        # Shift the image in some way
        if self.augmentations.translate_h:
            img = self.t_translate_h(img)
        if self.debug:
            time_th = time.time()
            time_th_diff = time_th - time_sp
            print("Translated horizontal. Time to process: {}".format(time_th_diff))
        if self.augmentations.translate_v:
            img = self.t_translate_v(img)
        if self.debug:
            time_tv = time.time()
            time_tv_diff = time_tv - time_th
            print("Translated vertical. Time to process: {}".format(time_tv_diff))
        if self.augmentations.rotate:
            img = self.t_rotate(img)
        if self.debug:
            time_rot = time.time()
            time_rot_diff = time_rot - time_tv
            print("Rotated frames. Time to process: {}".format(time_rot_diff))
        if self.augmentations.zoom:
            img = self.t_zoom(img)
        if self.debug:
            time_zoom = time.time()
            time_zoom_diff = time_zoom - time_rot
            print("Zoomed frames. Time to process: {}".format(time_zoom_diff))

        # Local changes
        if self.augmentations.local_blackout:
            img = self.t_local_blackout(img)
        if self.debug:
            time_lb = time.time()
            time_lb_diff = time_lb - time_rot
            print("Added local blackout. Time to process: {}".format(time_lb_diff))
        if self.augmentations.local_intensity:
            img = self.t_local_intensity(img)
        if self.debug:
            time_li = time.time()
            time_li_diff = time_li - time_lb
            print("Added local intensity. Time to process: {}".format(time_li_diff))

        return img.astype(np.float32)

    def transform_size(self, img, fps, hr, rwaves):
        '''
        Transforms the size/shape of the input image in different ways.
        :param img: The multidimensional input image. Shape is assumed to be (L,H,W,C).
        :param fps: The frames per second of the original input.
        :param hr: The heartrate of the patient when the original input was recorded.
        :return: The transformed image.
        '''
        initial_shape = img.shape
        time_start = time.time()
        if self.transforms.grayscale:
            img = self.t_grayscale_mean(img)
        if self.debug:
            time_gf = time.time()
            time_gf_diff = time_gf - time_start
            print("Image size after grayscale: {}, Time to process: {}".format(img.shape, time_gf_diff))
        if self.transforms.rwave_data_only:
            rwave_diff, rwave_indexes = self.calc_rwave_data(rwaves)
        if self.transforms.rescale_fps or self.transforms.resize_frames or self.transforms.rescale_fphb:
            assert not (self.transforms.rescale_fps and self.transforms.rescale_fphb)
            # Rescale length by either fps or fphb
            if self.transforms.rescale_fps and not self.transforms.target_fps == fps:
                new_length = int(img.shape[0] * (self.transforms.target_fps/fps))
            elif self.transforms.rescale_fphb:
                if self.transforms.rwave_data_only:
                    curr_fphb = self.calc_rwave_fphb(rwave_diff, fps)
                else:
                    curr_fphb = self.calc_fphb(hr, fps)
                new_length = math.ceil(img.shape[0]*(self.transforms.target_fphb/curr_fphb))
                if new_length < self.transforms.target_fphb:
                    new_length = self.transforms.target_fphb
            else:
                new_length = img.shape[0]

            # Rescale size
            if self.transforms.resize_frames and not (img.shape[1] == self.transforms.target_height and
                                                      img.shape[2] == self.transforms.target_width):
                new_height = self.transforms.target_height
                new_width = self.transforms.target_width
            else:
                new_height = img.shape[1]
                new_width = img.shape[2]

            img = self.t_resize(img, new_length, new_height, new_width)

        if self.debug:
            time_rescale = time.time()
            time_fps_diff = time_rescale - time_gf
            print("Image size after rescaling: {}, Time to process: {}".format(img.shape, time_fps_diff))
        assert not (self.transforms.loop_length and self.transforms.crop_length and self.transforms.rwave_data_only)
        if self.transforms.crop_sides or self.transforms.crop_length:
            img = self.t_crop(img)
        if self.debug:
            time_crop = time.time()
            time_crop_diff = time_crop - time_rescale
            print("Image size after cropping: {}, Time to process: {}".format(img.shape, time_crop_diff))
        if self.transforms.rwave_data_only:
            new_fps = fps * (self.transforms.target_fphb / curr_fphb)
            img = self.t_crop_rwave(img, rwaves, rwave_indexes, new_fps)
        if self.transforms.loop_length:
            img = self.t_loop_length(img)
        if self.transforms.pad_length:
            img = self.t_pad_length(img)
        if self.debug:
            time_loop = time.time()
            time_loop_diff = time_loop - time_crop
            print("Image size after length looping: {}, Time to process: {}".format(img.shape, time_loop_diff))
        if img.shape != (self.transforms.target_length, self.transforms.target_height, self.transforms.target_width, img.shape[3]):
            raise ValueError("Final video after transformation is not correct shape. Current shape is {} Original shape is {}".format(img.shape, initial_shape))
        return img

    def t_grayscale_custom(self, img):
        '''
        Converts a RBG video/image into a grayscale one by using luminence numbers.
        :param img: The input image, shape assumed to be (L,H,W,C)
        :return: The transformed image in shape (L,H,W,1)
        '''
        # Luminence numbers for converting RGB to grayscale
        b = [0.2989, 0.5870, 0.1140]
        img = np.dot(img[..., :3], b)
        return np.expand_dims(img, axis=-1)

    def t_grayscale_cv2(self, img):
        '''
        Converts a RBG video/image into a grayscale one using the cv2.cvtColor method.
        :param img: The input image, shape assumed to be (L,H,W,C)
        :return: The transformed image in shape (L,H,W,1)
        '''
        new_img = np.zeros((img.shape[0], img.shape[1], img.shape[2]))
        for i, frame in enumerate(img):
            new_img[i] = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return np.expand_dims(new_img, axis=-1)

    def t_grayscale_mean(self, img):
        '''
        Converts a RBG video/image into a grayscale one by taking the mean over all channels.
        :param img: The input image, shape assumed to be (L,H,W,C)
        :return: The transformed image in shape (L,H,W,1)
        '''
        img = np.average(img, axis=-1)
        return img.astype(np.uint8)

    def t_normalize(self, img):
        '''
        Normalizes an image with values ranging from 0-255 into the range 0:1
        :param img: The input image to be transformed.
        :return: The image with values normalized to the new range in float format.
        '''
        return img.astype(np.float32) / 255

    def t_normalize_signed(self, img):
        '''
        Normalizes an image with values ranging from 0-255 into the range -1:1.
        :param img: The input image to be transformed.
        :return: The image with values normalized to the new range in float format.
        '''
        return ((img / 255.) * 2 - 1).astype(np.float32)

    def t_gaussian_noise(self, img):
        '''
        Applies gaussian noise to an input image.
        :param img: The input image to be transformed.
        :return: The image with added noise
        '''
        return random_noise(img, mode='gaussian', var=self.augmentations.gn_var)

    def t_salt_and_pepper(self, img):
        '''
        Applies salt and pepper noise to an input image.
        :param img: The input image to be transformed.
        :return: The image with added noise
        '''
        return random_noise(img, mode='s&p', amount=self.augmentations.salt_and_pepper_amount)

    def t_speckle(self, img):
        '''
        Applies speckle noise to an input image.
        :param img: The input image to be transformed.
        :return: The image with added noise
        '''
        return random_noise(img, mode='speckle', var=self.augmentations.speckle_var)

    def t_resize(self, img, target_length, target_height, target_width):
        '''
        Resizes the input image to the supplied length, height and width using interpolation.
        The number of channels is preserved.
        :param img: The input image, shape is assumed to be (L,H,W,C)
        :param target_length: The new length the input image will be resized into
        :param target_height: The new height the input image will be resized into
        :param target_width: The new width the input image will be resized into
        :return: The resized image with shape (target_length, target_height, target_width, C)
        '''
        return resize(img, (target_length, target_height, target_width), mode='constant', cval=self.black_val,
                      preserve_range=True, anti_aliasing=True).astype(np.uint8)

    def calc_fphb(self, hr, fps):
        '''
        Calculates frames per heartbeat based on heartrate data
        :param hr: The heartrate (int)
        :param fps: Frames per second (int)
        :return: Frames per heartbeat
        '''
        hbs = hr/60
        fphb = fps / hbs
        return fphb

    def calc_rwave_fphb(self, rwave_diff, fps):
        '''
        Calculates frames per heartbeat based on rwave data
        :param rwave_diff: The length of a heartbeat in seconds, calculated from rwave data
        :param fps: Frames per second (int)
        :return: Frames per heartbeat
        '''
        hbs = 1 / rwave_diff
        fphb = fps / hbs
        return fphb

    def t_pad_size(self, img):
        '''
        Pads the frames of an image by adding black borders around it using the target sizes in the class object.
        :param img: The input image with shape (L,H,W,C)
        :return: The image with the new shape (L, self.transforms.target_height, self.transforms.target_width, C)
        '''
        # Pad edges of frames
        if self.transforms.target_height > img.shape[1] or self.transforms.target_width > img.shape[2]:
            pad_sequence = ((0, 0),
                            (int((self.transforms.target_height - img.shape[1])/2),
                            int((self.transforms.target_height - img.shape[1])/2)),
                            (int((self.transforms.target_width - img.shape[2])/2),
                             int((self.transforms.target_width - img.shape[2])/2)),
                            (0, 0))
            img = np.pad(img, pad_width=pad_sequence, constant_values=self.black_val)
        return img

    def t_pad_length(self, img):
        '''
        Pads the length (end) of a sequence by adding black frames.
        :param img: The input image with shape (L,H,W,C)
        :return: The image with the new shape (self.transforms.target_length,H,W,C)
        '''
        diff = self.transforms.target_length - img.shape[0]
        if diff > 0:
            pad_sequence = ((0, diff), (0, 0), (0, 0), (0, 0))
            img = np.pad(img, pad_width=pad_sequence, constant_values=self.black_val)
        return img

    def t_loop_length(self, img):
        '''
        Extends the duration of an image sequence by looping it until a target length has been reached.
        :param img: The input image to be looped with the shape (L,H,W,C)
        :return: The transformed image with the shape (self.transforms.target_length, H, W, C).
        '''
        org_img = img
        while len(img) < self.transforms.target_length:
            if len(org_img) <= self.transforms.target_length - len(img):
                img = np.append(img, org_img, axis=0)
            else:
                img = np.append(img, org_img[0:self.transforms.target_length - len(img)], axis=0)
        return img.astype(np.uint8)

    def t_crop(self, img):
        '''
        Randomly crops the video length to a fixed length.
        :param img: Input image to be cropped with shape (L,H,W,C)
        :return: The cropped image with shape (self.transforms.target_length,H,W,C)
        '''
        # Crop edges of frames
        crop_sequence = [(0, 0), (0, 0), (0, 0), (0, 0)]
        if self.transforms.crop_length and img.shape[0] > self.transforms.target_length:
            diff = img.shape[0] - self.transforms.target_length
            crop_sequence[0] = (0, diff)
        return crop(img, crop_width=tuple(crop_sequence)).astype(np.uint8)

    def t_crop_rwave(self, video, rwaves, rwave_indexes, fps):
        '''
        Crops the length of the input video the frames between the selected rwaves.
        The length of the video is equal to the frames per heartbeat value that the video is normalized to.
        :param video: Input video to be cropped with shape (L,H,W,C)
        :param rwaves: Array with timestamps for rwaves in milliseconds
        :param rwave_indexes: The indexes of the selected rwaves
        :param fps: The fps of the input video
        :return: The cropped image with shape (fphb,H,W,C)
        '''
        # Base case
        if video.shape[0] == self.transforms.target_fphb:
            return video
        start_frame = int((rwaves[rwave_indexes[0]] / 1000) * fps)
        end_frame = int((rwaves[rwave_indexes[1]] / 1000) * fps)
        # Need to fix some croppings as int rounding makes some videos 1 frame too long or too short
        if end_frame > video.shape[0]:
            end_frame -= 1
            start_frame -= 1
        if (end_frame - start_frame) < self.transforms.target_fphb:
            #print("Current length incorrect. Shape: {} Start: {} End: {}".format(video.shape, start_frame, end_frame))
            if end_frame < video.shape[0]:
                end_frame += 1
            elif start_frame > 0:
                start_frame -= 1
            else:
                raise ValueError("Cannot extend crop into correct shape")
        elif (end_frame - start_frame) > self.transforms.target_fphb:
            #print("Current length incorrect. Shape: {} Start: {} End: {}".format(video.shape, start_frame, end_frame))
            if start_frame < (end_frame - 1):
                start_frame += 1
            elif end_frame > (start_frame + 1):
                end_frame -= 1
            else:
                raise ValueError("Cannot extend crop into correct shape")
        rwave_frames = video[start_frame:end_frame]
        return rwave_frames

    def t_translate_v(self, video):
        '''
        Translates the frames of the input image sequence randomly vertically. Adding black pixels in the new areas.
        :param video: The image sequence to augment with shape (L,H,W,C)
        :return: The image sequence with the same shape (L,H,W,C) but each frame has been translated.
        '''
        t_len = int(np.random.normal(0, self.augmentations.translate_v_std_dev_pxl))

        video = video.transpose(3, 0, 1, 2)

        final_video = np.full_like(video, self.black_val)
        for i, channel in enumerate(video):
            new_img = np.full_like(channel, self.black_val)
            for j, frame in enumerate(channel):
                translated_frame = np.full_like(frame, self.black_val)
                if t_len < 0:
                    translated_frame[0:t_len, :] = frame[-t_len:, :]
                elif t_len > 0:
                    translated_frame[t_len:, :] = frame[0:-t_len, :]
                else:
                    translated_frame = frame
                new_img[j] = translated_frame
            final_video[i] = new_img

        return final_video.transpose(1, 2, 3, 0)

    def t_translate_h(self, video):
        '''
        Translates the frames of the input image sequence randomly horizontally. Adding black pixels in the new areas.
        :param video: The image sequence to augment with shape (L,H,W,C)
        :return: The image sequence with the same shape (L,H,W,C) but each frame has been translated.
        '''
        t_len = int(np.random.normal(0, self.augmentations.translate_h_std_dev_pxl))

        video = video.transpose(3, 0, 1, 2)

        final_video = np.full_like(video, self.black_val)
        for i, channel in enumerate(video):
            new_img = np.full_like(channel, self.black_val)
            for j, frame in enumerate(channel):
                translated_frame = np.full_like(frame, self.black_val)
                if t_len < 0:
                    translated_frame[:, 0:t_len] = frame[:, -t_len:]
                elif t_len > 0:
                    translated_frame[:, t_len:] = frame[:, 0:-t_len]
                else:
                    translated_frame = frame
                new_img[j] = translated_frame
            final_video[i] = new_img
        return final_video.transpose(1, 2, 3, 0)

    def t_rotate(self, video):
        '''
        Rotates each frame in the input image sequence randomly.
        :param video: The image sequence to augment with shape (L,H,W,C)
        :return: The image sequence with the same shape (L,H,W,C) but each frame has been rotated.
        '''
        t_rotation = np.random.normal(0, self.augmentations.rotate_std_dev_degrees)

        video = video.transpose(3, 0, 1, 2)

        final_video = np.full_like(video, self.black_val)
        for i, channel in enumerate(video):
            new_img = np.full_like(channel, self.black_val)
            for j, frame in enumerate(channel):
                rotated_frame = rotate(frame, t_rotation, resize=False, mode='constant', cval=self.black_val, preserve_range=True)
                new_img[j] = rotated_frame
            final_video[i] = new_img
        return final_video.transpose(1, 2, 3, 0)

    def t_local_blackout(self, video):
        '''
        Adds a randomly sized rectangle with black pixels into the input image. The position of the box is
        the same in each frame.
        :param video: The image sequence to augment with shape (L,H,W,C)
        :return: The image sequence with the same shape (L,H,W,C) but each frame has the added black rectangle.
        '''

        bo_size_h = int(abs(np.random.normal(0, self.augmentations.blackout_h_std_dev)))
        bo_size_w = int(abs(np.random.normal(0, self.augmentations.blackout_w_std_dev)))

        bo_pos_h = np.random.randint(0, video.shape[1] - bo_size_h)
        bo_pos_w = np.random.randint(0, video.shape[2] - bo_size_w)

        video = video.transpose(3, 0, 1, 2)

        for i, channel in enumerate(video):
            for j, frame in enumerate(channel):
                frame[bo_pos_h:bo_pos_h+bo_size_h, bo_pos_w:bo_pos_w+bo_size_w] = self.black_val

        return video.transpose(1, 2, 3, 0)

    def t_local_intensity(self, video):
        '''
        Adds a randomly sized rectangle with increased or reduced intensity into the input image.
        The position of the box is the same in each frame.
        :param video: The image sequence to augment with shape (L,H,W,C)
        :return: The image sequence with the same shape (L,H,W,C) but each frame has the added local intensity.
        '''
        ints_size_h = int(abs(np.random.normal(0, self.augmentations.intensity_h_std_dev)))
        ints_size_w = int(abs(np.random.normal(0, self.augmentations.intensity_w_std_dev)))

        ints_pos_h = np.random.randint(0, video.shape[1] - ints_size_h)
        ints_pos_w = np.random.randint(0, video.shape[2] - ints_size_w)

        ints_val = np.random.normal(0, self.augmentations.intensity_var)

        video = video.transpose(3, 0, 1, 2)

        for i, channel in enumerate(video):
            for j, frame in enumerate(channel):
                frame[ints_pos_h:ints_pos_h+ints_size_h, ints_pos_w:ints_pos_w+ints_size_w] = \
                    frame[ints_pos_h:ints_pos_h+ints_size_h, ints_pos_w:ints_pos_w+ints_size_w] + ints_val
        video = np.clip(video, self.black_val, self.white_val)
        return video.transpose(1, 2, 3, 0)

    def calc_rwave_data(self, rwaves):
        max_diff = 0
        max_diff_indexes = (0, 0)
        for i, _ in enumerate(rwaves):
            if i != 0:
                diff = (rwaves[i] - rwaves[i - 1]) / 1000
                if diff > max_diff:
                    max_diff = diff
                    max_diff_indexes = (i - 1, i)
        return max_diff, max_diff_indexes

    def t_zoom(self, img):
        zoom_factor = 1 + np.random.normal(0, self.augmentations.zoom_factor_std_dev)
        # Sometimes normal distribution can give too extreme results.
        # In those cases we dont zoom.
        if zoom_factor < 0:
            zoom_factor = 1
        new_img = np.zeros_like(img)
        new_img = new_img + self.black_val
        diff_height = None
        diff_width = None
        for i, frame in enumerate(img):
            zoom_frame = rescale(frame, zoom_factor, mode='constant', cval=self.black_val, preserve_range=True,
                                 multichannel=True)
            # Calculate offsets for zoomed frame
            if diff_height is None or diff_width is None:
                diff_height = zoom_frame.shape[0] - img.shape[1]
                diff_width = zoom_frame.shape[1] - img.shape[2]
                # Base case
                if zoom_factor == 1 or (diff_height == 0 and diff_width == 0):
                    return img
                elif zoom_factor > 1:
                    diff_h_start = int(diff_height / 2)
                    diff_h_end = img.shape[1] + diff_h_start
                    diff_w_start = int(diff_width / 2)
                    diff_w_end = img.shape[2] + diff_w_start
                elif zoom_factor < 1:
                    diff_h_start = int(abs(diff_height) / 2)
                    diff_h_end = zoom_frame.shape[0] + diff_h_start
                    diff_w_start = int(abs(diff_width) / 2)
                    diff_w_end = zoom_frame.shape[1] + diff_w_start

            # Set new frame to zoomed frame
            if zoom_factor > 1:
                new_img[i] = zoom_frame[diff_h_start:diff_h_end, diff_w_start:diff_w_end, :]
            elif zoom_factor < 1:
                new_img[i, abs(diff_h_start):abs(diff_h_end), abs(diff_w_start):abs(diff_w_end), :] = zoom_frame
        return new_img

