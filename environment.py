import numpy as np

class RIS_MISO(object):
    def __init__(self,
                 num_antennas,
                 num_RIS_elements,
                 num_users,
                 channel_est_error=False,
                 AWGN_var=1e-2,
                 channel_noise_var=1e-2):

        self.M = num_antennas
        self.L = num_RIS_elements
        self.K = num_users

        # Ensure integer division
        self.L_t = self.L // 2
        self.L_r = self.L // 2
        self.K_t = self.K // 2
        self.K_r = self.K // 2

        self.channel_est_error = channel_est_error

        # assert self.M == self.K

        self.awgn_var = AWGN_var
        self.channel_noise_var = channel_noise_var

        power_size = 2 * self.K
        channel_size = 2 * (self.L * self.M + self.L * self.K)

        self.action_dim = 2 * self.M * self.K + 2 * self.L
        self.state_dim = power_size + channel_size + self.action_dim

        self.H_1 = None
        self.H_2 = None
        self.h_t = None
        self.h_r = None
        # self.G = np.eye(self.M, dtype=complex)

        self.G = np.random.randn(self.M, self.K) + 1j * np.random.randn(self.M, self.K)
        trace_GGH = np.trace(self.G @ (self.G.conj().T))
        scaling_factor = np.sqrt(self.K / trace_GGH)
        self.G *= scaling_factor

        self.Phi = np.eye(self.L, dtype=complex)

        self.state = None
        self.done = None

        self.episode_t = None

    def _compute_tilde(self, matrix):
        return matrix.T @ self.Phi @ self.H_1 @ self.G

    def reset(self):
        self.episode_t = 0

        self.H_1 = np.random.normal(0, np.sqrt(0.5), (self.L, self.M)) + 1j * np.random.normal(0, np.sqrt(0.5), (self.L, self.M))
        self.h_t = np.random.normal(0, np.sqrt(0.5), (self.L, self.K_r)) + np.random.normal(0, np.sqrt(0.5), (self.L, self.K_r)) * 1j
        self.h_r = np.random.normal(0, np.sqrt(0.5), (self.L, self.K_t)) + np.random.normal(0, np.sqrt(0.5), (self.L, self.K_t)) * 1j

        init_action_G = np.hstack((np.real(self.G.reshape(1, -1)), np.imag(self.G.reshape(1, -1))))
        init_action_Phi = np.hstack((np.real(np.diag(self.Phi)).reshape(1, -1), np.imag(np.diag(self.Phi)).reshape(1, -1)))

        init_action = np.hstack((init_action_G, init_action_Phi))

        Phi_real = init_action[:, -2 * self.L:-self.L]
        Phi_imag = init_action[:, -self.L:]

        self.Phi = np.eye(self.L, dtype=complex) * (Phi_real + 1j * Phi_imag)

        power_t = np.real(np.diag(self.G.conjugate().T @ self.G)).reshape(1, -1) ** 2

        h_t_tilde = self._compute_tilde(self.h_t)
        h_r_tilde = self._compute_tilde(self.h_r)
        power_r = np.linalg.norm(h_t_tilde, axis=0).reshape(1, -1) ** 2 + np.linalg.norm(h_r_tilde, axis=0).reshape(1, -1) ** 2

        H_1_real, H_1_imag = np.real(self.H_1).reshape(1, -1), np.imag(self.H_1).reshape(1, -1)
        h_t_real, h_t_img = np.real(self.h_t).reshape(1, -1), np.imag(self.h_t).reshape(1, -1)
        h_r_real, h_r_img = np.real(self.h_r).reshape(1, -1), np.imag(self.h_r).reshape(1, -1)

        self.state = np.hstack((init_action, power_t, power_r, H_1_real, H_1_imag, h_t_real, h_t_img, h_r_real, h_r_img))

        return self.state

    def _compute_reward(self, Phi):

        diag_Phi = np.diag(Phi)
        diag_Phi1 = np.zeros((self.L,), dtype=complex)
        diag_Phi2 = np.zeros((self.L,), dtype=complex)
        diag_Phi1[:self.L_t] = diag_Phi[:self.L_t]
        diag_Phi2[self.L_t:] = diag_Phi[self.L_t:]

        Phi1 = np.diag(diag_Phi1)
        Phi2 = np.diag(diag_Phi2)
        reward = 0
        opt_reward = 0

        for k in range(self.K):
            if k < self.K_t:
                h = self.h_t
                Phi_k = Phi1
                h_k = h[:, k].reshape(-1, 1)
            else:
                h = self.h_r
                Phi_k = Phi2
                h_k = h[:, k-self.K_t].reshape(-1, 1)


            g_k = self.G[:, k].reshape(-1, 1)

            x = np.abs(h_k.T @ Phi_k @ self.H_1 @ g_k) ** 2
            x = x.item()

            G_removed = np.delete(self.G, k, axis=1)
            interference = np.sum(np.abs(h_k.T @ Phi_k @ self.H_1 @ G_removed) ** 2)
            y = interference + (self.K - 1) * self.awgn_var

            rho_k = x / y

            reward += np.log(1 + rho_k) / np.log(2)
            opt_reward += np.log(1 + x / ((self.K - 1) * self.awgn_var)) / np.log(2)

        return reward, opt_reward

    def step(self, action):
        self.episode_t += 1

        action = action.reshape(1, -1)

        G_real = action[:, :self.M ** 2]
        G_imag = action[:, self.M ** 2:2 * self.M ** 2]

        Phi_real = action[:, -2 * self.L:-self.L]
        Phi_imag = action[:, -self.L:]

        self.G = G_real.reshape(self.M, self.K) + 1j * G_imag.reshape(self.M, self.K)
        self.Phi = np.eye(self.L, dtype=complex) * (Phi_real + 1j * Phi_imag)

        power_t = np.real(np.diag(self.G.conjugate().T @ self.G)).reshape(1, -1) ** 2

        h_t_tilde = self._compute_tilde(self.h_t)
        h_r_tilde = self._compute_tilde(self.h_r)

        power_r = np.linalg.norm(h_t_tilde, axis=0).reshape(1, -1) ** 2 + np.linalg.norm(h_r_tilde, axis=0).reshape(1, -1) ** 2

        H_1_real, H_1_imag = np.real(self.H_1).reshape(1, -1), np.imag(self.H_1).reshape(1, -1)
        h_t_real, h_t_img = np.real(self.h_t).reshape(1, -1), np.imag(self.h_t).reshape(1, -1)
        h_r_real, h_r_img = np.real(self.h_r).reshape(1, -1), np.imag(self.h_r).reshape(1, -1)

        self.state = np.hstack((action, power_t, power_r, H_1_real, H_1_imag, h_t_real, h_t_img, h_r_real, h_r_img))

        reward, opt_reward = self._compute_reward(self.Phi)

        done = opt_reward == reward

        return self.state, reward, done, None

    def close(self):
        pass
