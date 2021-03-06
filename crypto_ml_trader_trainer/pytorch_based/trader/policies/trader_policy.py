import math
import random

import torch
from torch import nn

from shared.environments.trading_action import TradingAction
from pytorch_based.trader.environments.market_environment_abstract import MarketEnvironmentAbstract
from pytorch_based.core.policy import Policy
from pytorch_based.core.pytorch_global_config import Device


class TraderPolicy(Policy):
    """
    Greedy policy, which only predicts valid actions.
    """

    _episodes_done: int = 0
    _N_ACTIONS = 3


    def __init__(self, env: MarketEnvironmentAbstract, policy_net: nn.Module, eps_start: float = 0.95, eps_end: float = 0.05, eps_decay: float = 200):
        self.eps_start = eps_start
        self.eps_end = eps_end
        self.eps_decay = eps_decay
        self.policy_net = policy_net
        self.env: MarketEnvironmentAbstract = env

    def next_episode(self):
        self._episodes_done += 1

    def decide(self, state: torch.Tensor) -> (torch.Tensor, bool):
        eps_threshold = self.eps_end + (self.eps_start - self.eps_end) * math.exp(
            -1. * self._episodes_done / self.eps_decay)
        sample = random.random()

        if sample > eps_threshold:
            return self.predict_action(state)
        else:
            action = random.sample(self.env.valid_moves(), 1)[0]
            return torch.tensor([[action.value]],  dtype=torch.long).to(Device.device)


    def predict_action(self, state: torch.tensor):
        with torch.no_grad():
            # t.max(1) will return
            # largest column value of each row.
            # second column on max result is index of where max element was
            # found, so we pick action with the larger expected reward.

            actions_tensor = self.policy_net(state)

            # The first action might not be legal. Then we choose the second best action.
            first_choice_action: torch.tensor = self.policy_net(state).max(1)[1].view(1,1)

            if TradingAction(first_choice_action.numpy()[0]) in self.env.valid_moves():
                return first_choice_action.view(1, 1)

            actions_tensor[0][first_choice_action] = 0
            second_choice_action = self.policy_net(state).max(1)[1]

            # If the second is not valid, then we give up and just hold.
            if TradingAction(second_choice_action.numpy()[0]) in self.env.valid_moves():
                return second_choice_action.view(1, 1)

            return torch.tensor([[TradingAction.HOLD.value]]).to(Device.device).view(1, 1)
