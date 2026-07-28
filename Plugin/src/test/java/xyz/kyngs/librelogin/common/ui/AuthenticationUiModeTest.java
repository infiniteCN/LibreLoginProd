/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.common.ui;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class AuthenticationUiModeTest {

    @Test
    void 新客户端优先使用原生对话框() {
        assertEquals(
                AuthenticationUiMode.DIALOG, AuthenticationUiMode.choose(true, true, true, true));
    }

    @Test
    void 老客户端会退回铁砧() {
        assertEquals(
                AuthenticationUiMode.ANVIL, AuthenticationUiMode.choose(true, true, true, false));
    }

    @Test
    void 对话框手动关闭后也会退回铁砧() {
        assertEquals(
                AuthenticationUiMode.ANVIL, AuthenticationUiMode.choose(true, false, true, true));
    }

    @Test
    void 所有界面都关了就保留聊天命令() {
        assertEquals(
                AuthenticationUiMode.CHAT, AuthenticationUiMode.choose(true, false, false, true));
        assertEquals(
                AuthenticationUiMode.CHAT, AuthenticationUiMode.choose(false, true, true, true));
    }
}
