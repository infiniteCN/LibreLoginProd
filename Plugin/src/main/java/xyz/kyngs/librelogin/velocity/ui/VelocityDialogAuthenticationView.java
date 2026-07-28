/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.velocity.ui;

import static xyz.kyngs.librelogin.common.config.ConfigurationKeys.*;

import com.github.retrooper.packetevents.PacketEvents;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.ConnectionState;
import com.github.retrooper.packetevents.protocol.chat.clickevent.CustomClickEvent;
import com.github.retrooper.packetevents.protocol.dialog.CommonDialogData;
import com.github.retrooper.packetevents.protocol.dialog.DialogAction;
import com.github.retrooper.packetevents.protocol.dialog.MultiActionDialog;
import com.github.retrooper.packetevents.protocol.dialog.action.DynamicCustomAction;
import com.github.retrooper.packetevents.protocol.dialog.action.StaticAction;
import com.github.retrooper.packetevents.protocol.dialog.body.PlainMessage;
import com.github.retrooper.packetevents.protocol.dialog.body.PlainMessageDialogBody;
import com.github.retrooper.packetevents.protocol.dialog.button.ActionButton;
import com.github.retrooper.packetevents.protocol.dialog.button.CommonButtonData;
import com.github.retrooper.packetevents.protocol.dialog.input.Input;
import com.github.retrooper.packetevents.protocol.dialog.input.TextInputControl;
import com.github.retrooper.packetevents.protocol.nbt.NBT;
import com.github.retrooper.packetevents.protocol.nbt.NBTByte;
import com.github.retrooper.packetevents.protocol.nbt.NBTCompound;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.resources.ResourceLocation;
import com.github.retrooper.packetevents.wrapper.configuration.server.WrapperConfigServerClearDialog;
import com.github.retrooper.packetevents.wrapper.configuration.server.WrapperConfigServerShowDialog;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientCustomClickAction;
import com.github.retrooper.packetevents.wrapper.play.server.WrapperPlayServerClearDialog;
import com.github.retrooper.packetevents.wrapper.play.server.WrapperPlayServerShowDialog;
import com.velocitypowered.api.proxy.Player;
import java.util.ArrayList;
import java.util.List;
import net.kyori.adventure.text.Component;
import xyz.kyngs.librelogin.common.config.HoconPluginConfiguration;
import xyz.kyngs.librelogin.common.ui.AuthenticationUiState;

/** 新客户端的原生登录页。玩家虽然站在 NanoLimbo，窗口其实是代理直接发过去的。 */
final class VelocityDialogAuthenticationView {

    private static final String NAMESPACE = "librelogin";
    private static final ResourceLocation LOGIN_ACTION =
            new ResourceLocation(NAMESPACE, "ui/login");
    private static final ResourceLocation REGISTER_ACTION =
            new ResourceLocation(NAMESPACE, "ui/register");

    private final VelocityAuthenticationUiController controller;
    private final HoconPluginConfiguration configuration;

    VelocityDialogAuthenticationView(
            VelocityAuthenticationUiController controller, HoconPluginConfiguration configuration) {
        this.controller = controller;
        this.configuration = configuration;
    }

    void open(Player player, AuthenticationUiState state, Component feedback) {
        var registered = state.registered();
        var inputs = new ArrayList<Input>();
        inputs.add(input("password", configuration.get(AUTHENTICATION_UI_PASSWORD_LABEL), 128));

        if (registered && state.totpRequired()) {
            inputs.add(input("totp", configuration.get(AUTHENTICATION_UI_TOTP_LABEL), 8));
        } else if (!registered) {
            inputs.add(input("confirm", configuration.get(AUTHENTICATION_UI_CONFIRM_LABEL), 128));
        }

        var action = registered ? LOGIN_ACTION : REGISTER_ACTION;
        var title =
                configuration.get(
                        registered
                                ? AUTHENTICATION_UI_LOGIN_TITLE
                                : AUTHENTICATION_UI_REGISTER_TITLE);
        var tip =
                feedback != null
                        ? feedback
                        : Component.text(
                                configuration.get(
                                        registered
                                                ? AUTHENTICATION_UI_LOGIN_TIP
                                                : AUTHENTICATION_UI_REGISTER_TIP));
        var submitText =
                configuration.get(
                        registered
                                ? AUTHENTICATION_UI_LOGIN_BUTTON
                                : AUTHENTICATION_UI_REGISTER_BUTTON);

        var body = new PlainMessageDialogBody(new PlainMessage(tip, 220));
        var common =
                new CommonDialogData(
                        Component.text(title),
                        null,
                        false,
                        true,
                        DialogAction.CLOSE,
                        List.of(body),
                        inputs);

        var submit =
                new ActionButton(
                        new CommonButtonData(Component.text(submitText), Component.empty(), 150),
                        new DynamicCustomAction(action, null));

        var closePayload = new NBTCompound();
        closePayload.setTag("close", new NBTByte((byte) 1));
        var close =
                new ActionButton(
                        new CommonButtonData(
                                Component.text(controller.closeButtonText()),
                                Component.empty(),
                                150),
                        new StaticAction(new CustomClickEvent(action, closePayload)));

        var dialog =
                new MultiActionDialog(
                        common,
                        List.of(submit, close),
                        null,
                        configuration.get(AUTHENTICATION_UI_HORIZONTAL_BUTTONS) ? 2 : 1);

        var packetUser = PacketEvents.getAPI().getPlayerManager().getUser(player);
        if (packetUser == null) return;

        var connectionState = packetUser.getEncoderState();
        if (connectionState == ConnectionState.CONFIGURATION) {
            packetUser.sendPacket(new WrapperConfigServerShowDialog(dialog));
        } else if (connectionState == ConnectionState.PLAY) {
            packetUser.sendPacket(new WrapperPlayServerShowDialog(dialog));
        }
    }

    void close(Player player) {
        var packetUser = PacketEvents.getAPI().getPlayerManager().getUser(player);
        if (packetUser == null) return;

        var connectionState = packetUser.getEncoderState();
        if (connectionState == ConnectionState.CONFIGURATION) {
            // 转大厅时客户端已经回配置阶段了，再塞 Play 包就会多出 1 字节，26.2 当场翻脸。
            packetUser.sendPacket(new WrapperConfigServerClearDialog());
        } else if (connectionState == ConnectionState.PLAY) {
            packetUser.sendPacket(new WrapperPlayServerClearDialog());
        }
    }

    boolean handle(PacketReceiveEvent event) {
        if (event.getPacketType() != PacketType.Play.Client.CUSTOM_CLICK_ACTION) return false;
        if (!(event.getPlayer() instanceof Player player)) return false;

        var packet = new WrapperPlayClientCustomClickAction(event);
        var id = packet.getId();
        var login = LOGIN_ACTION.equals(id);
        var register = REGISTER_ACTION.equals(id);
        if (!login && !register) return false;

        event.setCancelled(true);
        NBT rawPayload = packet.getPayload();
        if (!(rawPayload instanceof NBTCompound payload)) {
            controller.showInternalError(player);
            return true;
        }

        if (payload.getBooleanOr("close", false)) {
            controller.handleClose(player);
            return true;
        }

        var password = payload.getStringTagValueOrDefault("password", "");
        if (login) {
            controller.submitLogin(
                    player, password, payload.getStringTagValueOrDefault("totp", ""));
        } else {
            controller.submitRegistration(
                    player, password, payload.getStringTagValueOrDefault("confirm", ""));
        }
        return true;
    }

    private Input input(String key, String label, int maxLength) {
        return new Input(
                key, new TextInputControl(150, Component.text(label), true, "", maxLength, null));
    }
}
