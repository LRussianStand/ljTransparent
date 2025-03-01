from __future__ import print_function
import argparse
import paddle
import time
import os
import dataLoader
from paddle.io import DataLoader
from utils import *
from mesh import create_mesh, GenMeshfromSDF, CalChamferDis
import logging
import os.path as osp
import cv2


parser = argparse.ArgumentParser()
# The locationi of training set
parser.add_argument('--dataRoot', default='/mnt/data3/lj/transparent/Data/Images%d/test', help='path to images')
parser.add_argument('--shapeRoot', default='/mnt/data3/lj/transparent/Data/Shapes/test/', help='path to images')
parser.add_argument('--experiment', default='./result/10-ball-ssim_0.001-12-ml-3-m+s+l/',
                    help='the path to store samples and models')
parser.add_argument('--testRoot', default=None, help='the path to store outputs')
# The basic training setting
parser.add_argument('--nepoch', type=int, default=10, help='the number of epochs for training')
parser.add_argument('--batchSize', type=int, default=None, help='input batch size')
parser.add_argument('--imageHeight', type=int, default=192, help='the height / width of the input image to network')
parser.add_argument('--imageWidth', type=int, default=256, help='the height / width of the input image to network')
parser.add_argument('--envHeight', type=int, default=1024, help='the height / width of the input envmap to network')
parser.add_argument('--envWidth', type=int, default=2048, help='the height / width of the input envmap to network')
# The parameters
parser.add_argument('--camNum', type=int, default=10, help='the number of views to create the visual hull')
parser.add_argument('--sampleNum', type=int, default=1, help='the sample num for the cost volume')
parser.add_argument('--shapeStart', type=int, default=3, help='the start id of the shape')
parser.add_argument('--shapeEnd', type=int, default=4, help='the end id of the shape')
parser.add_argument('--isAddCostVolume', action='store_true', help='whether to use cost volume or not')
parser.add_argument('--poolingMode', type=int, default=2, help='0: maxpooling, 1: average pooling 2: learnable pooling')
parser.add_argument('--isNoErrMap', action='store_true', help='whether to remove the error map in the input')
# The rendering parameters
parser.add_argument('--eta1', type=float, default=1.0003, help='the index of refraction of air')
parser.add_argument('--eta2', type=float, default=1.4723, help='the index of refraction of glass')
parser.add_argument('--fov', type=float, default=63.23, help='the x-direction full field of view of camera')
# The loss parameters
parser.add_argument('--normalWeight', type=float, default=1.0, help='the weight for normal')
# The gpu setting
parser.add_argument('--cuda', action='store_true', help='enables cuda')
parser.add_argument('--deviceIds', type=int, nargs='+', default=[2], help='the gpus used for training network')
parser.add_argument('--lr', type=float, default=0.0001, help='learning rate')
parser.add_argument('--ball', type=float, default=1, help='whether to use ball as initia shape')
parser.add_argument('--gridsize', type=int, default=12, help='learning rate')
parser.add_argument('--maskloss', type=float, default=1, help='whether to use mask loss')
parser.add_argument('--wi', type=float, default=1, help='weight for image loss')
parser.add_argument('--ws', type=float, default=1, help='weight for sdf loss')
parser.add_argument('--wl', type=float, default=1, help='weight for laplacian loss')
parser.add_argument('--stepNum', type=int, default=1500, help='the step number for each iteration')

paddle.set_printoptions(precision=8)
#设置打印的精度
opt = parser.parse_args()
print(opt)
dir_name = opt.experiment
if not os.path.isdir(dir_name):
    os.mkdir(dir_name)
if not os.path.isfile(opt.experiment + 'log.txt'):
    os.mknod(opt.experiment + 'log.txt')
logger = logging.getLogger()
logger.setLevel('INFO')
BASIC_FORMAT = "%(asctime)s:%(levelname)s:%(message)s"
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
formatter = logging.Formatter(BASIC_FORMAT, DATE_FORMAT)
fhlr = logging.FileHandler(opt.experiment + 'log.txt')
fhlr.setFormatter(formatter)
logger.addHandler(fhlr)

logger.info(opt)

opt.gpuId = opt.deviceIds[0]
if not 'real' in opt.dataRoot:
    opt.dataRoot = opt.dataRoot % opt.camNum

nw = opt.normalWeight
if opt.batchSize is None:
    opt.batchSize = opt.camNum

if __name__ == "__main__":


    brdfDataset = dataLoader.BatchLoader(
        opt.dataRoot, shapeRoot=opt.shapeRoot,
        imHeight=opt.imageHeight, imWidth=opt.imageWidth,
        envHeight=opt.envHeight, envWidth=opt.envWidth,
        isRandom=False, phase='TEST', rseed=1,
        isLoadVH=True, isLoadEnvmap=True, isLoadCam=True,
        shapeRs=opt.shapeStart, shapeRe=opt.shapeEnd,
        camNum=opt.camNum, batchSize=opt.camNum, isLoadSDF=True, grid_res=opt.gridsize, bounding_radius=1.1)
    brdfLoader = DataLoader(brdfDataset, batch_size=1, num_workers=0, shuffle=False)

    j = 0
    epoch = opt.nepoch
    for i, dataBatch in enumerate(brdfLoader):
        j += 1
        # Load ground-truth from cpu to gpu

        seg1_cpu = dataBatch['seg1'].squeeze(0)
        seg1Batch = seg1_cpu.cuda()

        # Load the image from cpu to gpu
        im_cpu = dataBatch['im'].squeeze(0)
        imBatch = im_cpu.cuda()

        imBg_cpu = dataBatch['imE'].squeeze(0)
        imBgBatch = imBg_cpu.cuda()

        # Load environment map
        envmap_cpu = dataBatch['env'].squeeze(0)
        envBatch = envmap_cpu.cuda()

        # Load camera parameters
        origin_cpu = dataBatch['origin'].squeeze(0)
        originBatch = origin_cpu.cuda()

        lookat_cpu = dataBatch['lookat'].squeeze(0)
        lookatBatch = lookat_cpu.cuda()

        up_cpu = dataBatch['up'].squeeze(0)
        upBatch = up_cpu.cuda()

        # Load visual hull data
        normal1VH_cpu = dataBatch['normal1VH'].squeeze(0)
        normal1VHBatch = normal1VH_cpu.cuda()

        seg1VH_cpu = dataBatch['seg1VH'].squeeze(0)
        seg1VHBatch = seg1VH_cpu.cuda()

        normal2VH_cpu = dataBatch['normal2VH'].squeeze(0)
        normal2VHBatch = normal2VH_cpu.cuda()

        seg2VH_cpu = dataBatch['seg2VH'].squeeze(0)
        seg2VHBatch = seg2VH_cpu.cuda()

        grid_vh_cpu = dataBatch['grid'].squeeze(0)
        grid_vh = grid_vh_cpu.cuda()

        grid_gt_cpu = dataBatch['gt_grid'].squeeze(0)
        grid_gt = grid_gt_cpu.cuda()

        shapePath = dataBatch['shape_path'][0]
        batchSize = imBgBatch.shape[0] #10

        # ---------------------------------------------------------------------------------------------------------------
        # define the folder name for results
        channelNum = imBgBatch.shape[1]#3
        cuda = True
        print(cuda)
        # paddle.to_tensor
        # # Tensor = torch.cuda.FloatTensor if cuda else paddle.FloatTensor
        width = opt.imageWidth
        height = opt.imageHeight

        # bounding box
        bounding_box_min_x = -1.1
        bounding_box_min_y = -1.1
        bounding_box_min_z = -1.1
        bounding_box_max_x = 1.1
        bounding_box_max_y = 1.1
        bounding_box_max_z = 1.1

        # initialize the grid
        # define the resolutions of the multi-resolution part
        voxel_res_list = [24,32, 40, 48, 56, 64, 96, 128, 256]
        # grid_res_x = grid_res_y = grid_res_z = voxel_res_list.pop(0)
        grid_res_x = grid_res_y = grid_res_z = opt.gridsize
        voxel_size = paddle.to_tensor([(bounding_box_max_x - bounding_box_min_x) / (grid_res_x - 1)])

        # Construct the sdf grid
        if (opt.ball):
            grid_initial = grid_construction_sphere_small(grid_res_x, bounding_box_min_x, bounding_box_max_x,
                                                          opt.ball)  ####
        else:
            grid_initial = grid_gt.float()

        # set parameters
        sdf_diff_list = []
        time_list = []
        image_loss = 1000 * batchSize
        sdf_loss = 1000 * batchSize
        iterations = 0
        scale = 1
        start_time = time.time()
        learning_rate = opt.lr
        tolerance = 1e-5

        chamfer_dis = CalChamferDis(osp.join(shapePath, 'visualHullSubd_%d.ply' % (opt.camNum)),
                                    osp.join(shapePath, 'object.obj'))
        logger.info('visual hull dis %.8f' % (chamfer_dis))
        # Calculate the mask of the gt
        image_bg = getBackground_bs(batchSize, height, width, opt.fov, opt.envHeight, opt.envWidth, originBatch, lookatBatch, upBatch, envBatch.permute(0, 2, 3, 1)).permute(0, 3, 1, 2)

        #
        image_bgnp = image_bg.numpy()
        for i in range(len(image_bgnp)):
            cv2.imwrite(dir_name + "grid_" + str(i+1) + "_bg.png", image_bgnp[i])
        # torchvision.utils.save_image(image_bg, #"./" +
        #                                dir_name + "grid_res_" + str(grid_res_x) + "_bg.png", nrow=5,
        #                               padding=2, normalize=False, range=None,
        #                               scale_each=False, pad_value=0)

        # train

        start_time = time.time()
        grid_loss_start = paddle.sum(paddle.abs(grid_initial - grid_gt)).item()
        while (grid_res_x <= 256):
            # tolerance *= 1.05
            # output initial images
            grid_initial.requires_grad = False
            image_initial, attmask, mask, inter_min_index,fine_pos = generate_image_bs(bounding_box_min_x, bounding_box_min_y,
                                                                              bounding_box_min_z,
                                                                              bounding_box_max_x, bounding_box_max_y,
                                                                              bounding_box_max_z,
                                                                              voxel_size,
                                                                              grid_res_x, grid_res_y, grid_res_z,
                                                                              batchSize, width,
                                                                              height,
                                                                              grid_initial,
                                                                              opt.fov / 2, originBatch,
                                                                              lookatBatch, upBatch,
                                                                              opt.eta1,
                                                                              opt.eta2, envBatch.permute(0, 2, 3, 1),
                                                                              opt.envHeight, opt.envWidth)
            image_initial = image_initial.permute(0, 3, 1, 2)
            image_initialnp = image_initial.numpy()
            for i in range(len(image_initialnp)):
                cv2.imwrite("./" + dir_name + "grid_" + str(i + 1) + "_start.png", image_initialnp[i])
            imBgBatchnp = imBgBatch.numpy()
            for i in range(len(imBgBatchnp)):
                cv2.imwrite("./" + dir_name + "grid_" + str(i + 1) + "_gt.png", imBgBatchnp[i])
            # torchvision.utils.save_image(image_initial,
            #                              "./" + dir_name + "grid_res_" + str(grid_res_x) + "_start.png", nrow=5,
            #                              padding=2, normalize=False, range=None,
            #                              scale_each=False, pad_value=0)
            # torchvision.utils.save_image(imBgBatch,
            #                              "./" + dir_name + "grid_res_" + str(grid_res_x) + "_gt.png", nrow=5, padding=2,
            #                              normalize=False, range=None,
            #                              scale_each=False, pad_value=0)

            # deform initial SDf to target SDF
            i = 0
            loss_camera = 1000
            loss = 1000
            average = 100000
            grid_loss_last = grid_loss_start

            grid_initial.requires_grad = True
            # optimizer = torch.optim.Adam([grid_initial], lr=learning_rate, eps=1e-8)
            optimizer = paddle.optim.SGD([grid_initial], lr=learning_rate)
            watch_grid = grid_initial.data.cpu().numpy()
            watch_gt = grid_gt.data.cpu().numpy()

            coord_x = paddle.linspace(0, grid_res_x - 1, grid_res_x).cuda() * voxel_size + bounding_box_min_x
            coord_y = paddle.linspace(0, grid_res_y - 1, grid_res_y).cuda() * voxel_size + bounding_box_min_y
            coord_z = paddle.linspace(0, grid_res_z - 1, grid_res_z).cuda() * voxel_size + bounding_box_min_z
            grid_x,grid_y,grid_z = paddle.meshgrid([coord_x,coord_y,coord_z])
            grid_xyz = paddle.stack((grid_x,grid_y,grid_z),dim=-1)


            while (loss < average - tolerance / 2 or i < opt.stepNum):
                average = loss

                optimizer.zero_grad()

                # Generate images
                image_initial, attmask, mask, inter_min_index,fine_pos = generate_image_bs(bounding_box_min_x,
                                                                                  bounding_box_min_y,
                                                                                  bounding_box_min_z,
                                                                                  bounding_box_max_x,
                                                                                  bounding_box_max_y,
                                                                                  bounding_box_max_z,
                                                                                  voxel_size,
                                                                                  grid_res_x, grid_res_y, grid_res_z,
                                                                                  batchSize,
                                                                                  width, height,
                                                                                  grid_initial,
                                                                                  opt.fov / 2, originBatch,
                                                                                  lookatBatch, upBatch,
                                                                                  opt.eta1,
                                                                                  opt.eta2,
                                                                                  envBatch.permute(0, 2, 3, 1),
                                                                                  opt.envHeight, opt.envWidth)
                # image_initial = (torch.clamp(refractImg + reflectImg, 0, 1)).data.permute(2, 0, 1)
                image_initial = image_initial.permute(0, 3, 1, 2)
                # Perform backprobagation
                # compute image loss and sdf loss
                image_loss, sdf_loss = loss_fn_ssim_bs(
                    image_initial * (1 - attmask).permute(0, 3, 1, 2).repeat(1, 3, 1, 1),
                    imBgBatch * (1 - attmask).permute(0, 3, 1, 2).repeat(1, 3, 1, 1), grid_initial,
                    voxel_size, grid_res_x, grid_res_y, grid_res_z,
                    batchSize, width, height)

                # compute laplacian loss
                conv_input = (grid_initial).unsqueeze(0).unsqueeze(0)
                conv_filter = paddle.to_tensor([[[[[0, 0, 0], [0, 1, 0], [0, 0, 0]],
                                                        [[0, 1, 0], [1, -6, 1], [0, 1, 0]],
                                                        [[0, 0, 0], [0, 1, 0], [0, 0, 0]]]]])
                Lp_loss = paddle.sum(F.conv3d(conv_input, conv_filter) ** 2) / (
                        grid_res_x * grid_res_y * grid_res_z * voxel_size * voxel_size)


                # get total loss
                b = 10
                if grid_res_x <= 32:
                    b = 100
                loss = opt.wi * image_loss + opt.ws * sdf_loss + opt.wl * Lp_loss
                loss_camera = image_loss + sdf_loss

                # print out loss messages
                print("lap loss:", Lp_loss.item())
                print("grid res:", grid_res_x, "iteration:", i, "loss:", loss.item())

                loss.backward()
                watch_grad_total = grid_initial.grad.cpu().numpy()
                watch_grid = grid_initial.data.cpu().numpy()

                optimizer.step()
                if grid_res_x == opt.gridsize:
                    # grid_loss = paddle.sum(paddle.abs(grid_initial - grid_gt)).item()
                    grid_loss = np.sum(np.abs(grid_initial.data.cpu().numpy() - grid_gt.data.cpu().numpy())).item()
                    print("lr: %f grid_loss: %f grid_loss_change: %f grid_loss_total_change: %f" % (opt.lr,
                                                                                                    grid_loss,
                                                                                                    grid_loss - grid_loss_last,
                                                                                                    grid_loss - grid_loss_start))
                    grid_loss_last = grid_loss
                i += 1

                if i % 100 == 0:
                    image_initial_np = image_initial.numpy()
                    for i in range(len(image_initial_np)):
                        cv2.imwrite("./" + dir_name + "grid_" + str(i + 1) +  "_" + str(
                                                     i / 100) +  ".png", image_initial_np[i])

                    # torchvision.utils.save_image(image_initial,
                    #                              "./" + dir_name + "grid_res_" + str(grid_res_x) + "_" + str(
                    #                                  i / 100) + ".png", nrow=5,
                    #                              padding=2, normalize=False, range=None,
                    #                              scale_each=False, pad_value=0)

            # genetate result images
            grid_initial.requires_grad = False
            print("%.8f" % (loss - average))
            image_initial, attmask, mask, inter_min_index, fine_pos = generate_image_bs(bounding_box_min_x, bounding_box_min_y,
                                                                              bounding_box_min_z,
                                                                              bounding_box_max_x, bounding_box_max_y,
                                                                              bounding_box_max_z,
                                                                              voxel_size,
                                                                              grid_res_x, grid_res_y, grid_res_z,
                                                                              batchSize,
                                                                              width, height,
                                                                              grid_initial,
                                                                              opt.fov / 2, originBatch,
                                                                              lookatBatch, upBatch,
                                                                              opt.eta1,
                                                                              opt.eta2, envBatch.permute(0, 2, 3, 1),
                                                                              opt.envHeight, opt.envWidth)
            image_initial = (paddle.clamp(image_initial, 0, 1)).data.permute(0, 3, 1, 2)
            image_initial_np = image_initial.numpy()
            for i in range(len(image_initial_np)):
                cv2.imwrite("./" + dir_name + "grid_" + str(i + 1) + "_final.png", image_initial_np[i])
            # torchvision.utils.save_image(image_initial,
            #                              "./" + dir_name + "grid_res_" + str(grid_res_x) + "_final.png", nrow=5,
            #                              padding=2, normalize=False, range=None,
            #                              scale_each=False, pad_value=0)

            # Save the final SDF result
            with open("./" + dir_name + str(grid_res_x) + ".pt", 'wb') as f:

                paddle.save(grid_initial, f)
                GenMeshfromSDF(grid_initial, bounding_box_max_x, "./" + dir_name + str(grid_res_x) + ".ply")
                chamfer_dis = CalChamferDis("./" + dir_name + str(grid_res_x) + ".ply",
                                            osp.join(shapePath, 'object.obj'))
                logger.info('%d dis %.8f' % (grid_res_x, chamfer_dis))

                # moves on to the next resolution stage
            if grid_res_x < 256:

                grid_res_update = voxel_res_list.pop(0)
                while grid_res_update < grid_res_x:
                    grid_res_update = voxel_res_list.pop(0)
                grid_res_update_x = grid_res_update_y = grid_res_update_z = grid_res_update
                voxel_size_update = (bounding_box_max_x - bounding_box_min_x) / (grid_res_update_x - 1)
                grid_initial_update = paddle.to_tensor(grid_res_update_x, grid_res_update_y, grid_res_update_z)
                linear_space_x = paddle.linspace(0, grid_res_update_x - 1, grid_res_update_x)
                linear_space_y = paddle.linspace(0, grid_res_update_y - 1, grid_res_update_y)
                linear_space_z = paddle.linspace(0, grid_res_update_z - 1, grid_res_update_z)
                first_loop = linear_space_x.repeat(grid_res_update_y * grid_res_update_z, 1).t().contiguous().view(
                    -1).unsqueeze_(1)
                second_loop = linear_space_y.repeat(grid_res_update_z, grid_res_update_x).t().contiguous().view(
                    -1).unsqueeze_(1)
                third_loop = linear_space_z.repeat(grid_res_update_x * grid_res_update_y).unsqueeze_(1)
                loop = paddle.cat((first_loop, second_loop, third_loop), 1).cuda()
                min_x = paddle.to_tensor([bounding_box_min_x]).repeat(
                    grid_res_update_x * grid_res_update_y * grid_res_update_z, 1)
                min_y = paddle.to_tensor([bounding_box_min_y]).repeat(
                    grid_res_update_x * grid_res_update_y * grid_res_update_z, 1)
                min_z = paddle.to_tensor([bounding_box_min_z]).repeat(
                    grid_res_update_x * grid_res_update_y * grid_res_update_z, 1)
                bounding_min_matrix = paddle.cat((min_x, min_y, min_z), 1)

                # Get the position of the grid points in the refined grid
                points = bounding_min_matrix + voxel_size_update * loop
                voxel_min_point_index_x = paddle.floor((points[:, 0].unsqueeze_(1) - min_x) / voxel_size).clamp(
                    max=grid_res_x - 2)
                voxel_min_point_index_y = paddle.floor((points[:, 1].unsqueeze_(1) - min_y) / voxel_size).clamp(
                    max=grid_res_y - 2)
                voxel_min_point_index_z = paddle.floor((points[:, 2].unsqueeze_(1) - min_z) / voxel_size).clamp(
                    max=grid_res_z - 2)
                voxel_min_point_index = paddle.cat(
                    (voxel_min_point_index_x, voxel_min_point_index_y, voxel_min_point_index_z), 1)
                voxel_min_point = bounding_min_matrix + voxel_min_point_index * voxel_size

                # Compute the sdf value of the grid points in the refined grid
                grid_initial_update = calculate_sdf_value(grid_initial, points, voxel_min_point,
                                                          voxel_min_point_index, voxel_size, grid_res_x, grid_res_y,
                                                          grid_res_z).view(grid_res_update_x, grid_res_update_y,
                                                                           grid_res_update_z)

                # Update the grid resolution for the refined sdf grid
                grid_res_x = grid_res_update_x
                grid_res_y = grid_res_update_y
                grid_res_z = grid_res_update_z

                # Update the voxel size for the refined sdf grid
                voxel_size = voxel_size_update

                # Update the sdf grid
                grid_initial = grid_initial_update.data

                # Double the size of the image
                if width < 256:
                    width = int(width * 2)
                    height = int(height * 2)
                learning_rate /= 1.4
            else:
                grid_res_x *= 2

        print("Time:", time.time() - start_time)

        print("----- END -----")
