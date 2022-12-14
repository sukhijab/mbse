"""Pendulum Swing-up Environment with full observation."""
import numpy as np
from mbse.models.reward_model import RewardModel
from mbse.models.dynamics_model import DynamicsModel
from gym.envs.classic_control.pendulum import PendulumEnv, angle_normalize
import jax.numpy as jnp
import jax
from functools import partial


class PendulumReward(RewardModel):
    """Get Pendulum Reward."""

    def __init__(self, ctrl_cost_weight=0.001, sparse=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ctrl_cost_weight = ctrl_cost_weight
        self.sparse = sparse

    @staticmethod
    @jax.jit
    def state_non_sparse_reward(theta, omega):
        """Get sparse reward."""
        theta = angle_normalize(theta)
        return -(theta ** 2 + 0.1 * omega ** 2)

    @partial(jax.jit, static_argnums=0)
    def input_cost(self, u):
        return self.ctrl_cost_weight * (jnp.sum(jnp.square(u), axis=-1))

    @partial(jax.jit, static_argnums=0)
    def state_reward(self, state):
        """Compute reward associated with state dynamics."""
        theta, omega = jnp.arctan2(state[..., 1], state[..., 0]), state[..., 2]
        return self.state_non_sparse_reward(theta, omega)

    @partial(jax.jit, static_argnums=0)
    def predict(self, obs, action, next_obs=None, rng=None):
        return self.state_reward(state=obs) - self.input_cost(action)


class PendulumSwingUpEnv(PendulumEnv):
    """Pendulum Swing-up Environment."""

    def __init__(self, reset_noise_scale=0.01, ctrl_cost_weight=0.001, sparse=False):
        self.base_mujoco_name = "Pendulum-v1"

        super(PendulumSwingUpEnv, self).__init__(render_mode='human')
        self.reset_noise_scale = reset_noise_scale
        self.state = np.zeros(2)
        self.last_u = None
        self._reward_model = PendulumReward(
            ctrl_cost_weight=ctrl_cost_weight, sparse=sparse
        )

    def reset(self, seed=None):
        """Reset to fix initial conditions."""
        x0 = np.array([np.pi, 0])
        self.state = self.np_random.uniform(
            low=x0 - self.reset_noise_scale, high=x0 + self.reset_noise_scale
        )

        self.last_u = None
        info = {}
        return self._get_obs(), info

    def step(self, u):
        """Override step method of pendulum env."""
        reward = self._reward_model.predict(jnp.asarray(self._get_obs()), jnp.asarray(u))
        reward = np.asarray(reward)
        u = np.clip(u, -self.max_torque, self.max_torque)[0]
        self.last_u = u  # for rendering

        g = self.g
        m = self.m
        l = self.l
        dt = self.dt
        th, omega = self.state

        omega_dot = (3 * g / (2 * l) * np.sin(th) + 3.0 / (m * l**2) * u)

        new_omega = omega + omega_dot * dt
        new_theta = th + new_omega * dt  # Simplectic integration new_omega.

        new_omega = np.clip(new_omega, -self.max_speed, self.max_speed)

        self.state = np.array([new_theta, new_omega])
        next_obs = self._get_obs()
        return next_obs, reward, False, False, {}

    def reward_model(self):
        """Get reward model."""
        return self._reward_model


class PendulumDynamicsModel(DynamicsModel):
    def __init__(self, env: PendulumEnv):
        self.env = env

    @partial(jax.jit, static_argnums=0)
    def predict(self, obs, action, rng=None):
        u = jnp.clip(self.rescale_action(action), -self.env.max_torque, self.env.max_torque)[0]
        theta, omega = self._get_reduced_state(obs)

        g = self.env.g
        m = self.env.m
        l = self.env.l
        dt = self.env.dt
        th, omega = self._get_reduced_state(obs)

        omega_dot = (3 * g / (2 * l) * jnp.sin(th) + 3.0 / (m * l ** 2) * u)

        new_omega = omega + omega_dot * dt
        new_theta = theta + new_omega * dt  # Simplectic integration new_omega.

        new_omega = jnp.clip(new_omega, -self.env.max_speed, self.env.max_speed)

        new_state = jnp.asarray([new_theta, new_omega]).T
        next_obs = self._get_obs(new_state)
        return next_obs.T

    @staticmethod
    @jax.jit
    def _get_obs(state):
        theta, thetadot = state[..., 0], state[..., 1]
        return jnp.asarray([jnp.cos(theta), jnp.sin(theta), thetadot], dtype=jnp.float32)

    @staticmethod
    @jax.jit
    def _get_reduced_state(obs):
        cos_theta, sin_theta = obs[..., 0], obs[..., 1]
        theta = jnp.arctan2(sin_theta, cos_theta)
        return theta, obs[..., -1]

    @partial(jax.jit, static_argnums=0)
    def rescale_action(self, action):
        """Rescales the action affinely from  [:attr:`min_action`, :attr:`max_action`] to the action space of the base environment, :attr:`env`.

        Args:
            action: The action to rescale

        Returns:
            The rescaled action
        """
        action = jnp.clip(action, self.env.min_action, self.env.max_action)
        low = self.env.action_space.low
        high = self.env.action_space.high
        action = low + (high - low) * (
            (action - self.env.min_action) / (self.env.max_action - self.env.min_action)
        )
        action = jnp.clip(action, low, high)
        return action