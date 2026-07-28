/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.paper.ui;

import static xyz.kyngs.librelogin.common.config.ConfigurationKeys.*;

import com.github.retrooper.packetevents.PacketEvents;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
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
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientCustomClickAction;
import com.github.retrooper.packetevents.wrapper.play.server.WrapperPlayServerClearDialog;
import com.github.retrooper.packetevents.wrapper.play.server.WrapperPlayServerShowDialog;
import java.util.ArrayList;
import java.util.List;
import net.kyori.adventure.text.Component;
import org.bukkit.entity.Player;
import xyz.kyngs.librelogin.common.config.HoconPluginConfiguration;
import xyz.kyngs.librelogin.common.ui.AuthenticationUiState;

/** 1.21.6 之后原生就有对话框，能用官方控件就别拿资源包硬糊。 */
final class DialogAuthenticationView {

    private static final String NAMESPACE = "librelogin";
    private static final ResourceLocation LOGIN_ACTION =
            new ResourceLocation(NAMESPACE, "ui/login");
    private static final ResourceLocation REGISTER_ACTION =
            new ResourceLocation(NAMESPACE, "ui/register");

    private final AuthenticationUiController controller;
    private final HoconPluginConfiguration configuration;

    DialogAuthenticationView(
            AuthenticationUiController controller, HoconPluginConfiguration configuration) {
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
        if (packetUser != null) {
            packetUser.sendPacket(new WrapperPlayServerShowDialog(dialog));
        }
    }

    void close(Player player) {
        var packetUser = PacketEvents.getAPI().getPlayerManager().getUser(player);
        if (packetUser != null) {
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
