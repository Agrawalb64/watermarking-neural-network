import os, sys
import numpy as np
import tensorflow as tf
import sonnet as snt

from config import FLAGS
from input_ import Image, Watermark
from model import Upsampler, Downsampler, Blender, Extractor
from utils import draw_image
from tensorflow.python.platform import app
from scipy import io

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

class ClipImage(snt.AbstractModule):
    def __init__(self, axis=1, name='clip_image'):
        super(ClipImage, self).__init__(name=name)
        self._axis = axis

    def _build(self, inputs):
        if not inputs.get_shape().as_list()[0] == 1:
            raise AssertionError('batch size must be one')

        inputs = tf.squeeze(inputs, axis=0)
        spatial_dim = inputs.get_shape().as_list()[0:-1]
        outputs = tf.gather(inputs, list(range(0, spatial_dim[self._axis] // 2)), axis = self._axis)

        padding = [0] + [spatial_dim[self._axis] - spatial_dim[self._axis] // 2]
        padding = np.expand_dims(padding, axis=(-1))
        padding = np.pad(padding, ((0, 0), (1, 0)), 'constant', constant_values=(0,
                                                                                 0))
        padding = tf.constant(padding, tf.int32)
        outputs = tf.concat([tf.expand_dims((tf.pad(inp, padding)), axis=(-1)) for inp in tf.unstack(outputs, axis=(-1))],
          axis=(-1))

        with tf.control_dependencies([tf.equal(tf.shape(inputs), tf.shape(outputs))]):
            outputs = tf.expand_dims(outputs, axis=0)

        return outputs


def test_clipimage():
    original_image = Image('/data/yuming/watermark-data/image_paths.mat', 10)()
    clipimage = ClipImage()
    clipped_image = clipimage(original_image)

    writer = tf.summary.FileWriter('model-output', tf.get_default_graph())
    with tf.Session() as (sess):
        sess.run([tf.global_variables_initializer(), tf.local_variables_initializer()])
        original_image_val, clipped_image_val = sess.run([original_image, clipped_image])

        images = [{'data':np.squeeze(original_image_val[0, :, :, :].astype(np.uint8)), 'title': 'original image'},
                  {'data':np.squeeze(clipped_image_val[0, :, :, :].astype(np.uint8)), 'title': 'clipped image'}]
        image_str = draw_image(images)
        writer.add_summary(image_str, global_step=0)
    writer.close()


def main(unused_argv):
    if FLAGS.checkpoint_dir == '' or not os.path.exists(FLAGS.checkpoint_dir):
        raise ValueError('invalid checkpoint directory {}'.format(FLAGS.checkpoint_dir))

    checkpoint_dir = os.path.join(FLAGS.checkpoint_dir, '')

    if FLAGS.output_dir == '':
        raise ValueError('invalid output directory {}'.format(FLAGS.output_dir))
    elif not os.path.exists(FLAGS.output_dir):
        assert FLAGS.output_dir != FLAGS.checkpoint_dir
        os.makedirs(FLAGS.output_dir)

    print('reconstructing models and inputs.')
    image = Image('/data/yuming/watermark-data/image_paths.mat', FLAGS.image_seq)()
    wm = Watermark('/data/yuming/watermark-data/watermark.mat')()

    dim = [1, FLAGS.img_height, FLAGS.img_width, FLAGS.num_chans]
    image_upsampler = Upsampler(dim)
    wm_upsampler = Upsampler([1] + dim[1:])
    downsampler = Downsampler(dim)
    blender = Blender(dim)
    clipimage = ClipImage()
    extrator = Extractor(dim)

    image_upsampled = image_upsampler(image)
    wm_upsampled = wm_upsampler(wm)
    image_blended = blender(image_upsampled, wm_upsampled)
    image_downsampled = downsampler(image_blended)
    image_downsampled = clipimage(image_downsampled)
    wm_extracted = extrator(image_downsampled)
    
    saver = tf.train.Saver()
    writer = tf.summary.FileWriter(FLAGS.output_dir, tf.get_default_graph())    
    
    config = tf.ConfigProto(allow_soft_placement = True, log_device_placement = False)
    assert (FLAGS.gpus != ''), 'invalid GPU specification'
    config.gpu_options.visible_device_list = FLAGS.gpus

    with tf.Session(config = config) as sess:
        sess.run(tf.local_variables_initializer())

        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            # Restores from checkpoint
            saver.restore(sess, ckpt.model_checkpoint_path)
            # Assuming model_checkpoint_path looks something like:
            #   /my-favorite-path/cifar10_train/model.ckpt-0,
            # extract global_step from it.
            global_step = ckpt.model_checkpoint_path.split('/')[-1].split('-')[-1]
        else:
            print('No checkpoint file found')
            return

        image_val, wm_val, image_downsampled_val, wm_extracted_val = \
            sess.run([image, wm, image_downsampled, wm_extracted])

        images = [{'data': np.squeeze(image_downsampled_val[0, :, :, :].astype(np.uint8)), 'title': "watermarked image"},
                  {'data': np.squeeze(wm_extracted_val[0, :, :, :].astype(np.uint8)), 'title': "extracted watermark"}]
        
        image_str = draw_image(images)
        writer.add_summary(image_str, global_step = 0)

        io.savemat(os.path.join(FLAGS.output_dir, "clip-test-data.mat"), 
                   {"wm": wm_val, 'wm_extracted': wm_extracted_val})
                   
    writer.close()

if __name__ == '__main__':
    # test_clipimage()
    tf.app.run()
