from mbse.utils.replay_buffer import Transition


class DynamicsModel(object):
    def __init__(self, *args, **kwargs):
        pass

    def predict(self, obs, action, rng=None):
        pass

    def train_step(self, tran: Transition):
        pass
