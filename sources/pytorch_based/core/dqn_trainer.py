import copy
from dataclasses import dataclass
from itertools import count

import torch
from torch import nn
from torch.autograd.grad_mode import F
from torch.optim import Optimizer

from pytorch_based.core.Transition import Transition
from pytorch_based.core.policy import Policy
from pytorch_based.core.pytorch_global_config import PytorchGlobalConfig
from pytorch_based.core.replay_memory import ReplayMemory
from pytorch_based.trader.gym_envs.crypto_market.envs.crypto_market_indicators_environment import CryptoMarketIndicatorsEnvironment


@dataclass
class DQNTrainerParameters:
    batch_size: int = 32
    gamma: float = 0.999
    memory_size: int = 10000
    target_update: float = 10


class DQNTrainer:

    @property
    def batch_size(self):
        return self.parameters.batch_size

    @property
    def gamma(self):
        return self.parameters.gamma

    def __init__(self,
                 model: nn.Module,
                 environment: CryptoMarketIndicatorsEnvironment,
                 optimizer: Optimizer,
                 parameters: DQNTrainerParameters,
                 policy: Policy):
        self.memory = ReplayMemory(parameters.memory_size)
        self.target_net: nn.Module = model
        self.policy_net: nn.Module = copy.deepcopy(model)
        self.environment = environment
        self.optimizer = optimizer
        self.parameters = parameters
        self.policy = policy

    def train(self, num_episodes: int):
        for i_episode in range(num_episodes):
            # Initialize the environment and state
            self.environment.reset()
            state = self.environment.reset()

            for t in count():
                # Select and perform an action
                action = self.policy.decide(state)
                next_state, reward, done, _ = self.environment.step(action.item())
                reward = torch.tensor([reward], device=PytorchGlobalConfig.device)

                # Observe new state
                if done:
                    next_state = None

                # Store the transition in memory
                self.memory.push(state, action, next_state, reward)

                # Move to the next state
                state = next_state

                # Perform one step of the optimization (on the policy network)
                self.optimize_model()
                if done:
                    # episode_durations.append(t + 1)
                    # plot_durations()
                    break

            # Update the target network, copying all weights and biases in DQN
            if i_episode % self.parameters.target_update == 0:
                self.target_net.load_state_dict(self.policy_net.state_dict())


    def optimize_model(self):
        if len(self.memory) < self.batch_size:
            return
        transitions = self.memory.sample(self.batch_size)
        # Transpose the batch (see https://stackoverflow.com/a/19343/3343043 for
        # detailed explanation). This converts batch-array of Transitions
        # to Transition of batch-arrays.
        batch = Transition(*zip(*transitions))

        # Compute a mask of non-final states and concatenate the batch elements
        # (a final state would've been the one after which simulation ended)
        non_final_mask = torch.tensor(tuple(map(lambda s: s is not None,
                                                batch.next_state)), device=PytorchGlobalConfig.device, dtype=torch.bool)
        non_final_next_states = torch.cat([s for s in batch.next_state
                                           if s is not None])
        state_batch = torch.cat(batch.state)
        action_batch = torch.cat(batch.action)
        reward_batch = torch.cat(batch.reward)

        # Compute Q(s_t, a) - the model computes Q(s_t), then we select the
        # columns of actions taken. These are the actions which would've been taken
        # for each batch state according to policy_net
        state_action_values = self.policy_net(state_batch).gather(1, action_batch)

        # Compute V(s_{t+1}) for all next states.
        # Expected values of actions for non_final_next_states are computed based
        # on the "older" target_net; selecting their best reward with max(1)[0].
        # This is merged based on the mask, such that we'll have either the expected
        # state value or 0 in case the state was final.
        next_state_values = torch.zeros(self.batch_size, device=PytorchGlobalConfig.device)
        next_state_values[non_final_mask] = self.target_net(non_final_next_states).max(1)[0].detach()
        # Compute the expected Q values
        expected_state_action_values = (next_state_values * self.gamma) + reward_batch

        # Compute Huber loss
        loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1))

        # Optimize the model
        self.optimizer.zero_grad()
        loss.backward()
        for param in self.policy_net.parameters():
            param.grad.data.clamp_(-1, 1)
        self.optimizer.step()