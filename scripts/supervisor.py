#!/usr/bin/env python
'''
Changes Made:

What																						When					Who
Added Enum type for parallel state machine													3/10,1:45PM				Varun
Added food_items data type to store coordinates												3/10 4:29PM				Varun
Added subscriber callback functions for	all food items										3/10 5:21PM				Varun
Added MACROS for food labels																3/10 5:45PM				Varun
self.state defaults to MAN_EXPLORATION														3/10 8:45PM				Varun
Added WAIT4FOOD Mode and extended state functionality										3/10 9:14PM				Kshitij
Added Order string subscriber and string processig call back								3/10 9:15PM				Kshitij

'''


import rospy
import numpy as np
from gazebo_msgs.msg import ModelStates
from std_msgs.msg import Float32MultiArray, String, Bool
from geometry_msgs.msg import Twist, PoseArray, Pose2D, PoseStamped
from asl_turtlebot.msg import DetectedObject
import tf
import math
from enum import Enum

# if sim is True/using gazebo, therefore want to subscribe to /gazebo/model_states\
# otherwise, they will use a TF lookup (hw2+)
use_gazebo = rospy.get_param("sim")

# if using gmapping, you will have a map frame. otherwise it will be odom frame
mapping = rospy.get_param("map")


# threshold at which we consider the robot at a location
POS_EPS = .2
THETA_EPS = .3

# time to stop at a stop sign
STOP_TIME = 3

# time to stop at a food joint
STOP4FOOD_TIME = 5 

# minimum distance from a stop sign to obey it
STOP_MIN_DIST = .5

# time taken to cross an intersection
CROSSING_TIME = 3

# state machine modes, not all implemented
class Mode(Enum):
	IDLE = 1
	POSE = 2
	STOP = 3
	CROSS = 4
	NAV = 5
	WAIT4FOOD = 6


class State(Enum):
	MAN_EXPLORATION = 1
	AUT_EXPLORATION = 2
	PICKUP = 3
	DELIVERY = 4
	WAIT4ORDER = 5
	


BANANA_LABEL = 52
APPLE_LABEL = 53
SANDWICH_LABEL = 54
ORANGE_LABEL = 55
BROCCOLI_LABEL = 56
CARROT_LABEL = 57
HOT_DOG_LABEL = 58
PIZZA_LABEL = 59
DONUT_LABEL = 60
CAKE_LABEL = 61

FOOD_THRESHOLD_DISTANCE = 1	#if item is closer than this only then register
SAME_ITEM_THRESHOLD = 2 #if same food item was seen within this distance it is not unique

labels = {
		"banana": 52,
		"apple": 53,
		"sandwich": 54,
		"orange": 55,
		"broccoli": 56,
		"carrot": 57,
		"hot_dog": 58,
		"pizza": 59,
		"donut": 60,
		"cake": 61,
	}



print "supervisor settings:\n"
print "use_gazebo = %s\n" % use_gazebo
print "mapping = %s\n" % mapping

class Supervisor:

	def __init__(self):
		rospy.init_node('turtlebot_supervisor', anonymous=True)
		# initialize variables
		self.x = 0
		self.y = 0
		self.theta = 0
		self.orderList = []
		self.mode = Mode.IDLE
		self.state = State.MAN_EXPLORATION	# defaults to manual exploration
		self.last_mode_printed = None
		self.trans_listener = tf.TransformListener()
		# command pose for controller
		self.pose_goal_publisher = rospy.Publisher('/cmd_pose', Pose2D, queue_size=10)
		# nav pose for controller
		self.nav_goal_publisher = rospy.Publisher('/cmd_nav', Pose2D, queue_size=10)
		# command vel (used for idling)
		self.cmd_vel_publisher = rospy.Publisher('/cmd_vel', Twist, queue_size=10)
		
		self.food_items = []	#list of tuples for food items, (label,2Darray)
		

		# subscribers
		# food item detectors
		rospy.Subscriber('/detector/banana', DetectedObject, self.banana_detected_callback)
		rospy.Subscriber('/detector/hot_dog', DetectedObject, self.hot_dog_detected_callback)
		rospy.Subscriber('/detector/apple', DetectedObject, self.apple_detected_callback)
		rospy.Subscriber('/detector/sandwich', DetectedObject, self.sandwich_detected_callback)
		rospy.Subscriber('/detector/orange', DetectedObject, self.orange_detected_callback)
		rospy.Subscriber('/detector/pizza', DetectedObject, self.pizza_detected_callback)
		rospy.Subscriber('/detector/donut', DetectedObject, self.donut_detected_callback)
		rospy.Subscriber('/detector/cake', DetectedObject, self.cake_detected_callback)
		rospy.Subscriber('/detector/broccoli', DetectedObject, self.broccoli_detected_callback)
		rospy.Subscriber('/detector/carrot', DetectedObject, self.carrot_detected_callback)

		# stop sign detector
		rospy.Subscriber('/detector/stop_sign', DetectedObject, self.stop_sign_detected_callback)
		# high-level navigation pose
		rospy.Subscriber('/nav_pose', Pose2D, self.nav_pose_callback)
		# if using gazebo, we have access to perfect state
		if use_gazebo:
			rospy.Subscriber('/gazebo/model_states', ModelStates, self.gazebo_callback)
		# we can subscribe to nav goal click
		rospy.Subscriber('/move_base_simple/goal', PoseStamped, self.rviz_goal_callback)
		# subscribe to order message
		rospy.Subscriber('/delivery_request', String, self.message_processing_callback)
		
		# subscriber to receive message that exploration is done
		rospy.Subscriber('/exploration_complete', Bool, self.exploration_completed_callback)


	def gazebo_callback(self, msg):
		pose = msg.pose[msg.name.index("turtlebot3_burger")]
		twist = msg.twist[msg.name.index("turtlebot3_burger")]
		self.x = pose.position.x
		self.y = pose.position.y
		quaternion = (
					pose.orientation.x,
					pose.orientation.y,
					pose.orientation.z,
					pose.orientation.w)
		euler = tf.transformations.euler_from_quaternion(quaternion)
		self.theta = euler[2]


	def rviz_goal_callback(self, msg):
		""" callback for a pose goal sent through rviz """
		
		# Only follow rviz command when in manual exploration state
		print("got goal")

		if not self.state == State.MAN_EXPLORATION:
			return

		origin_frame = "/map" if mapping else "/odom"
		print("rviz command received!")
		try:
			
			nav_pose_origin = self.trans_listener.transformPose(origin_frame, msg)
			self.x_g = nav_pose_origin.pose.position.x
			self.y_g = nav_pose_origin.pose.position.y
			quaternion = (
					nav_pose_origin.pose.orientation.x,
					nav_pose_origin.pose.orientation.y,
					nav_pose_origin.pose.orientation.z,
					nav_pose_origin.pose.orientation.w)
			euler = tf.transformations.euler_from_quaternion(quaternion)
			self.theta_g = euler[2]
		except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
			pass
		self.mode = Mode.NAV
	

	def nav_pose_callback(self, msg):
		self.x_g = msg.x
		self.y_g = msg.y
		self.theta_g = msg.theta
		self.mode = Mode.NAV
	

	def stop_sign_detected_callback(self, msg):
		""" callback for when the detector has found a stop sign. Note that
		a distance of 0 can mean that the lidar did not pickup the stop sign at all """

		# distance of the stop sign
		dist = msg.distance

		# if close enough and in nav mode, stop
		if dist > 0 and dist < STOP_MIN_DIST and self.mode == Mode.NAV:
			self.init_stop_sign()
			

	def message_processing_callback(self,msg):
		orderString = msg.data
		self.orderList = orderString.split(',')
		print(self.orderList)
		

	def exploration_completed_callback(self, msg):
	  """
	  Check's if exploration is completed. If it is: drive back home.
	  """
	  
	  exploration_complete = msg.data
	  
	  if exploration_complete:
		print(self.food_items)
		self.state_transition(State.DELIVERY)	#go home first


	def add_detected_item(self,dist,label):
		print("Detected item " + str(label))
		if(self.state == State.AUT_EXPLORATION or self.state == State.MAN_EXPLORATION):	
			print(dist)		
			size = len(self.food_items)
			new_item = True	#assume new food item
			for i in range(size):
				if(self.food_items[i][0] == label ):
					if(np.linalg.norm(self.food_items[i][1] - np.array([self.x,self.y]) ) < SAME_ITEM_THRESHOLD):
						new_item = False	#same food item if found in somewhat same location
						break					
			if(new_item):
				item = (label,np.array([self.x,self.y]))
				self.food_items.append(item)
				print("Item position" + str([self.x,self.y]))


	def banana_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, BANANA_LABEL)
		
				
	def apple_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, APPLE_LABEL)


	def sandwich_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, SANDWICH_LABEL)


	def orange_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, ORANGE_LABEL)
				
				
	def broccoli_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, BROCCOLI_LABEL)
				
	def carrot_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, CARROT_LABEL)
				
				
	def hot_dog_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, HOT_DOG_LABEL)
				
				
	def pizza_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, PIZZA_LABEL)
				
				
	def donut_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, DONUT_LABEL)
				
				
	def cake_detected_callback(self,msg):
		dist = msg.distance
		self.add_detected_item(dist, CAKE_LABEL)

	def get_next_label(self):
		next_id = self.orderList.pop(0)

		for i in range(len(self.food_items)):
			if(labels[next_id] == self.food_items[i][0]):
				print("Found" + str(next_id))
				return i


	def go_to_pose(self):
		""" sends the current desired pose to the pose controller """

		raise("Dont use this one")

		pose_g_msg = Pose2D()
		pose_g_msg.x = self.x_g
		pose_g_msg.y = self.y_g
		pose_g_msg.theta = self.theta_g

		self.pose_goal_publisher.publish(pose_g_msg)


	def nav_to_pose(self):
		""" sends the current desired pose to the naviagtor """

		nav_g_msg = Pose2D()
		nav_g_msg.x = self.x_g
		nav_g_msg.y = self.y_g
		nav_g_msg.theta = self.theta_g

		self.nav_goal_publisher.publish(nav_g_msg)


	def stay_idle(self):
		""" sends zero velocity to stay put """

		vel_g_msg = Twist()
		self.cmd_vel_publisher.publish(vel_g_msg)


	def close_to(self,x,y,theta):
		""" checks if the robot is at a pose within some threshold """

		return (abs(x-self.x)<POS_EPS and abs(y-self.y)<POS_EPS and abs(theta-self.theta)<THETA_EPS)


	def init_stop_sign(self):
		""" initiates a stop sign maneuver """

		self.stop_sign_start = rospy.get_rostime()
		self.mode = Mode.STOP


	def has_stopped(self):
		""" checks if stop sign maneuver is over """

		return (self.mode == Mode.STOP and (rospy.get_rostime()-self.stop_sign_start)>rospy.Duration.from_sec(STOP_TIME))


	def init_crossing(self):
		""" initiates an intersection crossing maneuver """

		self.cross_start = rospy.get_rostime()
		self.mode = Mode.CROSS


	def has_crossed(self):
		""" checks if crossing maneuver is over """

		return (self.mode == Mode.CROSS and (rospy.get_rostime()-self.cross_start)>rospy.Duration.from_sec(CROSSING_TIME))


	def init_stopped4food(self):
		""" stops for food pickup """
		self.stop4food_start = rospy.get_rostime()
		self.mode = Mode.WAIT4FOOD
	

	def has_stopped4food(self):
		""" checks if stopping for food is over """

		return (self.mode == Mode.WAIT4FOOD and (rospy.get_rostime()-self.stop4food_start)>rospy.Duration.from_sec(STOP4FOOD_TIME))
	  

	def set_nav_goal(self,x,y,theta):
		"changes the navigation goal pose based on State"
		self.x_g = x
		self.y_g = y
		self.theta_g = theta

	#----------------------------
	#	Here is the state machine
	#----------------------------
	def state_transition(self, new_state):

		self.state = new_state

		if(self.state == State.PICKUP):
			if len(self.orderList) > 0:
				next_food_label = self.get_next_label()

				self.set_nav_goal(self.food_items[next_food_label][1][0],self.food_items[next_food_label][1][1],0)	#go to the next food item
				self.mode = Mode.NAV
				print("Going to PICKUP state")
			else:
				print("Picked up all food, return home.")
				self.state_transition(State.DELIVERY)
				return
			
		elif(self.state == State.DELIVERY):
			self.set_nav_goal(0,0,np.pi)
			self.mode = Mode.NAV
			print("Going home.")

		elif(self.state == State.WAIT4ORDER):
			print("Waiting for new order")
			self.mode = Mode.IDLE
		
		else:
			print("Invalid state.")

	#----------------------------
	#	State machine ends
	#----------------------------

	def loop(self):
		""" the main loop of the robot. At each iteration, depending on its
		mode (i.e. the finite state machine's state), if takes appropriate
		actions. This function shouldn't return anything """

		if not use_gazebo:
			try:
				origin_frame = "/map" if mapping else "/odom"
				(translation,rotation) = self.trans_listener.lookupTransform(origin_frame, '/base_footprint', rospy.Time(0))
				self.x = translation[0]
				self.y = translation[1]
				euler = tf.transformations.euler_from_quaternion(rotation)
				self.theta = euler[2]
			except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
				pass
		

		
		# logs the current mode
		if not(self.last_mode_printed == self.mode):
			rospy.loginfo("Current Mode: %s", self.mode)
			self.last_mode_printed = self.mode

		# Arrives at this mode if task is done
		if self.mode == Mode.IDLE:
			
			#Back home
			if self.state == State.DELIVERY:
				self.state_transition(State.WAIT4ORDER)

			elif self.state == State.PICKUP:
				print("Arrived at pickup spot.")
				self.init_stopped4food()

			elif self.state == State.WAIT4ORDER and len(self.orderList) > 0:
				print("Recieved new order.")
				self.state_transition(State.PICKUP)

			else:
				self.stay_idle()

		elif self.mode == Mode.POSE:
			# moving towards a desired pose
			if self.close_to(self.x_g,self.y_g,self.theta_g):
				self.mode = Mode.IDLE
			else:
				self.go_to_pose()

		elif self.mode == Mode.STOP:
			# at a stop sign
			if self.has_stopped():
				self.init_crossing()
			else:
				self.stay_idle()

		elif self.mode == Mode.CROSS:
			# crossing an intersection
			if self.has_crossed():
				self.mode = Mode.NAV
			else:
				self.nav_to_pose()
		
		elif self.mode == Mode.WAIT4FOOD:
			#if picked up food
			if self.has_stopped4food():
				self.state_transition(State.PICKUP)
			else:
				self.stay_idle()

		elif self.mode == Mode.NAV:
			if self.close_to(self.x_g,self.y_g,self.theta_g):
				self.mode = Mode.IDLE
			else:
				self.nav_to_pose()

		else:
			raise Exception('This mode is not supported: %s'
				% str(self.mode))

	def run(self):
		rate = rospy.Rate(10) # 10 Hz
		while not rospy.is_shutdown():
			self.loop()
			rate.sleep()

if __name__ == '__main__':
	sup = Supervisor()
	sup.run()
