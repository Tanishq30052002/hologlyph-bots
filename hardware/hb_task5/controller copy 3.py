from os import error
from rclpy.node import Node
from geometry_msgs.msg import Pose2D, Twist
from std_msgs.msg import Bool

import numpy as np
import math


class HolonomicBotController(Node):
    def __init__(self, robot_id, goal_positions, goal_positions_theta, deadbands={'left':{'+':0, '-':0}, 'right':{'+':0, '-':0}, 'rear':{'+':0, '-':0}}):
        super().__init__(node_name=f'hb_{robot_id}_controller')
        self.robot_id = robot_id
        self.goal_positions = goal_positions
        self.goal_position_theta = goal_positions_theta
        self.deadbands=deadbands

        self.pose_subscriber = self.create_subscription(Pose2D, f'/pen{robot_id}_pose', self.pose_callback, 1)
        self.cmd_pub = self.create_publisher(Twist, f"/cmd_vel/bot{robot_id}", 1)
        self.pen_pub = self.create_publisher(Bool, f"/pen{robot_id}_down", 1)
        self.bot_status_pub = self.create_publisher(Bool, f"/finish/bot{robot_id}", 1)

        self.current_pose = Pose2D()
        self.command_twist = Twist()
        self.pen_status = Bool()
        self.bot_status = Bool()

        self.goal_index = 0
        self.reached_goal = False

        # PID
        self.prev_error_x = 0
        self.prev_error_y = 0
        self.prev_error_theta = 0
        self.integral_error_x = 0
        self.integral_error_y = 0
        self.integral_error_theta = 0

    def pose_callback(self, pose_msg):
        self.current_pose.x = pose_msg.x
        self.current_pose.y = pose_msg.y
        self.current_pose.theta = pose_msg.theta

    # def bound(self, value):
    #     # limit max values
    #     if value > 35:
    #         value = 35
    #     elif value < -35:
    #         value = -35

    #     return value
        
    def bound(self, a, b, c, thresh=35.0):
        maxi = max(a, max(b, c))
        if maxi<thresh:
            return a, b, c
        a = float(a/maxi)*thresh
        b = float(b/maxi)*thresh
        c = float(c/maxi)*thresh
        return a, b, c

    def deadband(self, value, wheel):
        if(value>0):
            value=value+self.deadbands[wheel]['+']
        elif(value<0):
            value=value-self.deadbands[wheel]['-']
        return value

    # def inverse_kinematics(self, linear_velocity_x, linear_velocity_y, angular_velocity):
    #     left_wheel_velocity = self.bound(self.deadband(angular_velocity / 3 - linear_velocity_x / 2 - linear_velocity_y * math.cos(math.pi / 6), 'left'))
    #     right_wheel_velocity = self.bound(self.deadband(angular_velocity / 3 - linear_velocity_x / 2 + linear_velocity_y * math.cos(math.pi / 6), 'right'))
    #     rear_wheel_velocity = self.bound(self.deadband(angular_velocity / 3 + 0.7 * linear_velocity_x, 'rear'))

    #     return float(left_wheel_velocity), float(right_wheel_velocity), float(rear_wheel_velocity)
    

    def inverse_kinematics(self, linear_velocity_x, linear_velocity_y, angular_velocity):
        left_wheel_velocity = self.deadband(angular_velocity / 3 - linear_velocity_x / 2 - linear_velocity_y * math.cos(math.pi / 6), 'left')
        right_wheel_velocity = self.deadband(angular_velocity / 3 - linear_velocity_x / 2 + linear_velocity_y * math.cos(math.pi / 6), 'right')
        rear_wheel_velocity = self.deadband(angular_velocity / 3 + 0.7 * linear_velocity_x, 'rear')

        left_wheel_velocity, right_wheel_velocity, rear_wheel_velocity = self.bound(left_wheel_velocity, right_wheel_velocity, rear_wheel_velocity)

        return float(left_wheel_velocity), float(right_wheel_velocity), float(rear_wheel_velocity)

    def control_robot(self):
        goal_x, goal_y = self.goal_positions[self.goal_index]
        goal_theta = self.goal_position_theta

        current_x, current_y, current_theta = self.current_pose.x, self.current_pose.y, self.current_pose.theta

        delta_x, delta_y, delta_theta = goal_x - current_x, goal_y - current_y, goal_theta - current_theta

        delta_x_bot_frame = -delta_y * math.sin(current_theta) + delta_x * math.cos(current_theta)
        delta_y_bot_frame = delta_x * math.sin(current_theta) + delta_y * math.cos(current_theta)
        delta_theta_bot_frame = delta_theta

        linear_error_threshold = 7.5
        angular_error_threshold = 0.25

        linear_velocity_x, linear_velocity_y, angular_velocity = 0, 0, 0
        pen_down = True if self.goal_index != 0 else False

        kp_x, kp_y, kp_theta = 1.0, 1.0, 80.0
        ki_x, ki_y , ki_theta = 0.0, 0.0, 0.0
        kd_x, kd_y, kd_theta = 5.0, 5.0, 0.0

        error_x = delta_x_bot_frame
        error_y = delta_y_bot_frame
        error_theta = delta_theta_bot_frame

        self.integral_error_x += error_x
        self.integral_error_y += error_y
        self.integral_error_theta += error_theta

        derivative_error_x = error_x - self.prev_error_x
        derivative_error_y = error_y - self.prev_error_y
        derivative_error_theta = error_theta - self.prev_error_theta
        
        if abs(delta_theta_bot_frame) > angular_error_threshold or math.sqrt((delta_x_bot_frame ** 2) + (delta_y_bot_frame ** 2)) > linear_error_threshold:
            # linear_velocity_x = kp_x * delta_x_bot_frame
            # linear_velocity_y = -kp_y * delta_y_bot_frame
            # angular_velocity = kp_theta * delta_theta_bot_frame

            linear_velocity_x = kp_x * error_x + ki_x * self.integral_error_x + kd_x * derivative_error_x
            linear_velocity_y = -kp_y * error_y - ki_y * self.integral_error_y - kd_y * derivative_error_y
            angular_velocity = kp_theta * error_theta + ki_theta * self.integral_error_theta + kd_theta * derivative_error_theta

            self.prev_error_x = error_x
            self.prev_error_y = error_y
            self.prev_error_theta = error_theta

        else:
            if self.goal_index < np.size(self.goal_positions, axis=0):
                self.goal_index += 1

            if self.goal_index == np.size(self.goal_positions, axis=0):
                linear_velocity_x, linear_velocity_y, angular_velocity = 0, 0, 0
                pen_down = False  # Goal Reached
                self.reached_goal = True
                self.goal_index -= 1

        left_wheel, right_wheel, rear_wheel = self.inverse_kinematics(linear_velocity_x, linear_velocity_y, angular_velocity)
        self.command_twist.linear.x = left_wheel
        self.command_twist.linear.y = right_wheel
        self.command_twist.linear.z = rear_wheel
        self.cmd_pub.publish(self.command_twist)
        
        self.pen_status.data = pen_down
        self.pen_pub.publish(self.pen_status)

        
        if self.reached_goal:
            self.bot_status.data=True
            # self.get_logger().info("Reached Goal")
        else:    
            self.bot_status.data=False
            self.get_logger().info(f"goal_x {round(goal_x,2)}, goal_y {round(goal_y,2)}, goal_theta {round(goal_theta,2)}")
            self.get_logger().info(f"current_x {round(current_x,2)}, current_y {round(current_y,2)}, current_theta {round(current_theta,2)}")
            self.get_logger().info(f"delta_x_bot {round(delta_x_bot_frame,2)}, delta_y_bot {round(delta_y_bot_frame,2)}, delta_theta_bot {round(delta_theta_bot_frame,2)}")
            self.get_logger().info(f"left_wheel {round(left_wheel,2)}, right_wheel {round(right_wheel,2)}, rear_wheel {round(rear_wheel,2)}")
            self.get_logger().info("#" * 50)

        self.bot_status_pub.publish(self.bot_status)