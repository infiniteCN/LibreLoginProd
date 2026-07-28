/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.common.ui;

/** 玩家这次该看到哪种登录页。单独拎出来，免得客户端版本判断散得到处都是。 */
public enum AuthenticationUiMode {
    DIALOG,
    ANVIL,
    CHAT;

    public static AuthenticationUiMode choose(
            boolean enabled,
            boolean dialogEnabled,
            boolean anvilEnabled,
            boolean clientSupportsDialog) {
        if (!enabled) return CHAT;
        if (dialogEnabled && clientSupportsDialog) return DIALOG;
        if (anvilEnabled) return ANVIL;
        return CHAT;
    }
}
