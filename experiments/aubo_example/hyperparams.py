# To get started, copy over hyperparams from another experiment.
# Visit rll.berkeley.edu/gps/hyperparams.html for documentation.
""" Hyperparameters for UR trajectory optimization experiment. """
from __future__ import division
import numpy as np
import os.path
import rospy
from datetime import datetime
from tf import TransformListener

from gps import __file__ as gps_filepath
from gps.agent.aubo_ros.agent_aubo import AgentAUBOROS
from gps.algorithm.algorithm_traj_opt import AlgorithmTrajOpt
from gps.algorithm.cost.cost_fk import CostFK
from gps.algorithm.cost.cost_sum import CostSum
from gps.algorithm.cost.cost_utils import RAMP_LINEAR, RAMP_FINAL_ONLY
from gps.algorithm.dynamics.dynamics_lr_prior import DynamicsLRPrior
from gps.algorithm.dynamics.dynamics_prior_gmm import DynamicsPriorGMM
from gps.algorithm.traj_opt.traj_opt_lqr_python import TrajOptLQRPython
from gps.algorithm.policy.lin_gauss_init import init_lqr
from gps.gui.target_setup_gui import load_pose_from_npz
from gps.proto.gps_pb2 import JOINT_ANGLES, JOINT_VELOCITIES, \
    END_EFFECTOR_POINTS, END_EFFECTOR_POINT_VELOCITIES, ACTION, \
    TRIAL_ARM, JOINT_SPACE
from gps.utility.general_utils import get_ee_points, get_position
from gps.gui.config import generate_experiment_info

# Topics for the robot publisher and subscriber.
JOINT_PUBLISHER = '/arm_controller/command'
JOINT_SUBSCRIBER = '/arm_controller/state'

# 'SLOWNESS' is how far in the future (in seconds) position control extrapolates
# when it publishs actions for robot movement.  1.0-10.0 is fine for simulation.
SLOWNESS = 10.0
# 'RESET_SLOWNESS' is how long (in seconds) we tell the robot to take when
# returning to its start configuration.
RESET_SLOWNESS = 2.0

# Set constants for joints
SHOULDER_JOINT = 'shoulder_joint'
UPPERARM_JOINT = 'upperArm_joint'
FOREARM_JOINT = 'foreArm_joint'
WRIST1_JOINT = 'wrist1_joint'
WRIST2_JOINT = 'wrist2_joint'
WRIST3_JOINT = 'wrist3_joint'

# Set constants for links
PEDESTAL_LINK = 'base_Link'
SHOULDER_LINK = 'shoulder_Link'
UPPER_ARM_LINK = 'upperArm_Link'
FOREARM_LINK = 'foreArm_Link'
WRIST1_LINK = 'wrist1_Link'
WRIST2_LINK = 'wrist2_Link'
WRIST3_LINK = 'wrist3_Link'

# Set end effector constants
INITIAL_JOINTS = [0, 0, 0, 0, 0, 0]

# Set the number of goal points. 1 by default for a single end effector tip.
NUM_EE_POINTS = 1
EE_POINTS = np.array([[0, 0, 0]])

# Specify a goal state in cartesian coordinates.
EE_POS_TGT = np.asmatrix([.30, -0.30, .80])
"""UR 10 Examples:
EE_POS_TGT = np.asmatrix([.29, .52, .62]) # Target where all joints are 0.
EE_POS_TGT = np.asmatrix([.65, .80, .30]) # Target in positive octant near ground.
EE_POS_TGT = np.asmatrix([.70, .70, .50]) # Target in positive octant used for debugging convergence.
The Gazebo sim converges to the above point with non-action costs: 
(-589.75, -594.71, -599.54, -601.54, -602.75, -603.28, -604.28, -604.79, -605.55, -606.29)
Distance from Goal: (0.014, 0.005, -0.017)
"""

# Set to identity unless you want the goal to have a certain orientation.
EE_ROT_TGT = np.asmatrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]])

# Only edit these when editing the robot joints and links.
# The lengths of these arrays define numerous parameters in GPS.
JOINT_ORDER = [SHOULDER_JOINT, UPPERARM_JOINT, FOREARM_JOINT,
               WRIST1_JOINT, WRIST2_JOINT, WRIST3_JOINT]
LINK_NAMES = [PEDESTAL_LINK, SHOULDER_LINK, UPPER_ARM_LINK, FOREARM_LINK,
              WRIST1_LINK, WRIST2_LINK, WRIST3_LINK]

# Hyperparamters to be tuned for optimizing policy learning on the specific robot.
AUBO_GAINS = np.array([1, 1, 1, 1, 1, 1])

# Packaging sensor dimensional data for refernece.
SENSOR_DIMS = {
    JOINT_ANGLES: len(JOINT_ORDER),
    JOINT_VELOCITIES: len(JOINT_ORDER),
    END_EFFECTOR_POINTS: NUM_EE_POINTS * EE_POINTS.shape[1],
    END_EFFECTOR_POINT_VELOCITIES: NUM_EE_POINTS * EE_POINTS.shape[1],
    ACTION: len(AUBO_GAINS),
}

# States to check in agent._process_observations.
STATE_TYPES = {'positions': JOINT_ANGLES,
               'velocities': JOINT_VELOCITIES}

# Path to urdf of robot.
TREE_PATH = '/home/eric/aubo_ws/src/aubo_robot/aubo_description/urdf/aubo_i5_robot.urdf'

# Be sure to specify the correct experiment directory to save policy data at.
BASE_DIR = '/'.join(str.split(gps_filepath, '/')[:-2])
EXP_DIR = BASE_DIR + '/../experiments/aubo_example/'

# Set the number of seconds per step of a sample.
TIMESTEP = 0.01  # Typically 0.01.
# Set the number of timesteps per sample.
STEP_COUNT = 100  # Typically 100.
# Set the number of samples per condition.
SAMPLE_COUNT = 5  # Typically 5.
# set the number of conditions per iteration.
CONDITIONS = 1  # Typically 2 for Caffe and 1 for LQR.
# Set the number of trajectory iterations to collect.
ITERATIONS = 10  # Typically 10.

x0s = []
ee_tgts = []
reset_conditions = []

common = {
    'experiment_name': 'my_experiment' + '_' + \
                       datetime.strftime(datetime.now(), '%m-%d-%y_%H-%M'),
    'experiment_dir': EXP_DIR,
    'data_files_dir': EXP_DIR + 'data_files/',
    'target_filename': EXP_DIR + 'target.npz',
    'log_filename': EXP_DIR + 'log.txt',
    'conditions': CONDITIONS,
}

# Set up each condition.
for i in xrange(common['conditions']):
    # Use hardcoded default vals init and target locations
    ja_x0 = np.zeros(SENSOR_DIMS[JOINT_ANGLES])
    ee_pos_x0 = np.zeros((1, 3))
    ee_rot_x0 = np.zeros((3, 3))

    ee_pos_tgt = EE_POS_TGT
    ee_rot_tgt = EE_ROT_TGT

    state_space = sum(SENSOR_DIMS.values()) - SENSOR_DIMS[ACTION]

    joint_dim = SENSOR_DIMS[JOINT_ANGLES] + SENSOR_DIMS[JOINT_VELOCITIES]

    # Initialized to start position and inital velocities are 0
    x0 = np.zeros(state_space)
    x0[:SENSOR_DIMS[JOINT_ANGLES]] = ja_x0

    # Need for this node will go away upon migration to KDL
    rospy.init_node('gps_agent_aubo_ros_node')

    # Set starting end effector position using TF
    tf = TransformListener()

    # Sleep for .1 secs to give the node a chance to kick off
    rospy.sleep(1)
    time = tf.getLatestCommonTime(WRIST3_LINK, PEDESTAL_LINK)

    x0[joint_dim:(joint_dim + NUM_EE_POINTS * EE_POINTS.shape[1])] = get_position(tf, WRIST3_LINK, PEDESTAL_LINK, time)

    # Initialize target end effector position
    ee_tgt = np.ndarray.flatten(
        get_ee_points(EE_POINTS, ee_pos_tgt, ee_rot_tgt).T
    )

    reset_condition = {
        JOINT_ANGLES: INITIAL_JOINTS,
        JOINT_VELOCITIES: []
    }

    x0s.append(x0)
    ee_tgts.append(ee_tgt)
    reset_conditions.append(reset_condition)

if not os.path.exists(common['data_files_dir']):
    os.makedirs(common['data_files_dir'])

agent = {
    'type': AgentAUBOROS,
    'dt': TIMESTEP,
    'dU': SENSOR_DIMS[ACTION],
    'conditions': common['conditions'],
    'T': STEP_COUNT,
    'x0': x0s,
    'ee_points_tgt': ee_tgts,
    'reset_conditions': reset_conditions,
    'sensor_dims': SENSOR_DIMS,
    'joint_order': JOINT_ORDER,
    'link_names': LINK_NAMES,
    'state_types': STATE_TYPES,
    'tree_path': TREE_PATH,
    'joint_publisher': JOINT_PUBLISHER,
    'joint_subscriber': JOINT_SUBSCRIBER,
    'slowness': SLOWNESS,
    'reset_slowness': RESET_SLOWNESS,
    'state_include': [JOINT_ANGLES, JOINT_VELOCITIES,
                      END_EFFECTOR_POINTS, END_EFFECTOR_POINT_VELOCITIES],
    'end_effector_points': [EE_POINTS],
    'obs_include': [],
}

algorithm = {
    'type': AlgorithmTrajOpt,
    'conditions': common['conditions'],
    'iterations': ITERATIONS,
}

algorithm['init_traj_distr'] = {
    'type': init_lqr,
    'init_gains': 1.0 / AUBO_GAINS,
    'init_acc': np.zeros(SENSOR_DIMS[ACTION]),
    'init_var': 1.0,
    'stiffness': 0.5,
    'stiffness_vel': .25,
    'final_weight': 50,
    'dt': agent['dt'],
    'T': agent['T'],
}

# This cost function takes into account the distance between the end effector's
# current and target positions, weighted in a linearly increasing fassion
# as the number of trials grows from 0 to T-1.
fk_cost_ramp = {
    'type': CostFK,
    # Target end effector is subtracted out of EE_POINTS in pr2 c++ plugin so goal
    # is 0. The UR agent also subtracts this out for consistency.
    'target_end_effector': [np.zeros(NUM_EE_POINTS * EE_POINTS.shape[1])],
    'wp': np.ones(SENSOR_DIMS[END_EFFECTOR_POINTS]),
    'l1': 0.1,
    'l2': 0.0001,
    'ramp_option': RAMP_LINEAR,
}

# This cost function takes into account the distance between the end effector's
# current and target positions at time T-1 only.
fk_cost_final = {
    'type': CostFK,
    'target_end_effector': np.zeros(NUM_EE_POINTS * EE_POINTS.shape[1]),
    'wp': np.ones(SENSOR_DIMS[END_EFFECTOR_POINTS]),
    'l1': 1.0,
    'l2': 0.0,
    'wp_final_multiplier': 100.0,  # Weight multiplier on final timestep.
    'ramp_option': RAMP_FINAL_ONLY,
}

# Combines the cost functions in 'costs' to produce a single cost function
algorithm['cost'] = {
    'type': CostSum,
    'costs': [fk_cost_ramp, fk_cost_final],
    'weights': [1.0, 1.0],
}

algorithm['dynamics'] = {
    'type': DynamicsLRPrior,
    'regularization': 1e-6,
    'prior': {
        'type': DynamicsPriorGMM,
        'max_clusters': 20,
        'min_samples_per_cluster': 40,
        'max_samples': 20,
    },
}

algorithm['traj_opt'] = {
    'type': TrajOptLQRPython,
}

algorithm['policy_opt'] = {}

config = {
    'iterations': algorithm['iterations'],
    'common': common,
    'verbose_trials': 0,
    'agent': agent,
    'gui_on': True,
    'algorithm': algorithm,
    'num_samples': SAMPLE_COUNT,
}

common['info'] = generate_experiment_info(config)
