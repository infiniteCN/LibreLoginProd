/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.common.ui;

/** 弹窗口只关心这两个状态，别把整份用户数据到处扔。 */
public record AuthenticationUiState(boolean registered, boolean totpRequired) {}
