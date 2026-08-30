/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.common.listener;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.UUID;
import org.junit.jupiter.api.Test;

class KnownUserPreLoginTest {

    @Test
    void 已登记离线账号直接走离线认证() {
        assertTrue(PreLoginIdentity.isKnownOfflineAccount(null));
    }

    @Test
    void 已登记正版账号仍然查询正版资料() {
        assertFalse(
                PreLoginIdentity.isKnownOfflineAccount(
                        UUID.fromString("8667ba71-b85a-4004-af54-457a9734eed7")));
    }
}
