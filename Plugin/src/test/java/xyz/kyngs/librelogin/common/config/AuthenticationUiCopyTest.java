/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.common.config;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import org.junit.jupiter.api.Test;
import xyz.kyngs.librelogin.common.config.key.ConfigurationKey;

class AuthenticationUiCopyTest {

    @Test
    void 登录界面文案保持简短() {
        var 文案 =
                List.of(
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_LOGIN_TITLE, "登录 infiniteMC"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_LOGIN_TIP, "输入密码，验证通过就会进入大厅。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_PASSWORD_LABEL, "密码"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_TOTP_LABEL, "验证码"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_TOTP_TIP, "再输入两步验证码。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_LOGIN_BUTTON, "登录"),
                        new 文案(
                                ConfigurationKeys.AUTHENTICATION_UI_LOGIN_FAILED,
                                "没登录上，检查一下密码或验证码。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_REGISTER_TITLE, "创建账号"),
                        new 文案(
                                ConfigurationKeys.AUTHENTICATION_UI_REGISTER_TIP,
                                "第一次来需要设置密码，下次登录还会用到。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_CONFIRM_LABEL, "确认密码"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_CONFIRM_TIP, "再输入一次刚才的密码。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_REGISTER_BUTTON, "完成注册"),
                        new 文案(
                                ConfigurationKeys.AUTHENTICATION_UI_REGISTER_FAILED,
                                "没注册上。检查一下两次密码是否一致，长度也别太短。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_CLOSE_BUTTON, "关闭窗口"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_EXIT_BUTTON, "退出服务器"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_EXIT_MESSAGE, "已取消登录。"),
                        new 文案(
                                ConfigurationKeys.AUTHENTICATION_UI_CLOSED_MESSAGE,
                                "登录窗口已关闭。你也可以输入 /login 或 /register 继续。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_EMPTY_INPUT, "先把密码输上。"),
                        new 文案(ConfigurationKeys.AUTHENTICATION_UI_BUSY, "上一次还没处理完，等一下再点。"),
                        new 文案(
                                ConfigurationKeys.AUTHENTICATION_UI_INTERNAL_ERROR,
                                "登录窗口没能正常打开，重新进服试一下。"));

        文案.forEach(一条 -> assertEquals(一条.内容(), 一条.配置().defaultValue()));
    }

    private record 文案(ConfigurationKey<String> 配置, String 内容) {}
}
