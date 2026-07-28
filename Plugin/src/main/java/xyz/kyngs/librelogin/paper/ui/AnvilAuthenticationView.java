/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.paper.ui;

import static xyz.kyngs.librelogin.common.config.ConfigurationKeys.*;

import com.github.retrooper.packetevents.PacketEvents;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.manager.server.ServerVersion;
import com.github.retrooper.packetevents.protocol.component.ComponentTypes;
import com.github.retrooper.packetevents.protocol.component.builtin.item.ItemLore;
import com.github.retrooper.packetevents.protocol.item.ItemStack;
import com.github.retrooper.packetevents.protocol.item.type.ItemType;
import com.github.retrooper.packetevents.protocol.item.type.ItemTypes;
import com.github.retrooper.packetevents.protocol.nbt.NBTCompound;
import com.github.retrooper.packetevents.protocol.nbt.NBTList;
import com.github.retrooper.packetevents.protocol.nbt.NBTString;
import com.github.retrooper.packetevents.protocol.nbt.NBTType;
import com.github.retrooper.packetevents.protocol.packettype.PacketType;
import com.github.retrooper.packetevents.protocol.player.User;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientClickWindow;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientCloseWindow;
import com.github.retrooper.packetevents.wrapper.play.client.WrapperPlayClientNameItem;
import com.github.retrooper.packetevents.wrapper.play.server.WrapperPlayServerOpenWindow;
import com.github.retrooper.packetevents.wrapper.play.server.WrapperPlayServerWindowItems;
import io.github.retrooper.packetevents.adventure.serializer.gson.GsonComponentSerializer;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.entity.Player;
import xyz.kyngs.librelogin.common.config.HoconPluginConfiguration;
import xyz.kyngs.librelogin.common.ui.AuthenticationUiState;

/** 旧客户端没有原生对话框，只能借铁砧输入。丑是丑了点，但稳。 */
final class AnvilAuthenticationView {

    private static final int WINDOW_ID = 58;
    private static final int STATE_ID = 0;

    private final AuthenticationUiController controller;
    private final HoconPluginConfiguration configuration;
    private final Map<UUID, Session> sessions = new ConcurrentHashMap<>();
    private final int anvilWindowType;

    AnvilAuthenticationView(
            AuthenticationUiController controller, HoconPluginConfiguration configuration) {
        this.controller = controller;
        this.configuration = configuration;
        this.anvilWindowType = resolveAnvilWindowType();
    }

    void open(Player player, AuthenticationUiState state, Component feedback) {
        var stage = state.registered() ? Stage.LOGIN_PASSWORD : Stage.REGISTER_PASSWORD;
        var session = new Session(state, stage, feedback);
        sessions.put(player.getUniqueId(), session);
        openSession(player, session, false);
    }

    void close(Player player) {
        sessions.remove(player.getUniqueId());
        var user = packetUser(player);
        if (user != null) user.closeInventory();
    }

    void forget(Player player) {
        sessions.remove(player.getUniqueId());
    }

    void clear() {
        sessions.clear();
    }

    boolean handle(PacketReceiveEvent event) {
        if (!(event.getPlayer() instanceof Player player)) return false;
        var session = sessions.get(player.getUniqueId());
        if (session == null) return false;

        if (event.getPacketType() == PacketType.Play.Client.NAME_ITEM) {
            session.input = new WrapperPlayClientNameItem(event).getItemName();
            refresh(player, session);
            return true;
        }

        if (event.getPacketType() == PacketType.Play.Client.CLICK_WINDOW) {
            var packet = new WrapperPlayClientClickWindow(event);
            if (packet.getWindowId() != WINDOW_ID) return false;

            event.setCancelled(true);
            var slot = packet.getSlot();
            if (slot == 0) {
                sessions.remove(player.getUniqueId());
                controller.handleClose(player);
            } else if (slot == 2) {
                submitStage(player, session);
            } else {
                refresh(player, session);
            }
            return true;
        }

        if (event.getPacketType() == PacketType.Play.Client.CLOSE_WINDOW) {
            var packet = new WrapperPlayClientCloseWindow(event);
            if (packet.getWindowId() != WINDOW_ID) return false;

            sessions.remove(player.getUniqueId());
            controller.handleClose(player);
            return true;
        }

        return false;
    }

    private void submitStage(Player player, Session session) {
        var value = session.input == null ? "" : session.input;
        switch (session.stage) {
            case LOGIN_PASSWORD -> {
                if (session.state.totpRequired()) {
                    session.firstValue = value;
                    session.input = "";
                    session.stage = Stage.LOGIN_TOTP;
                    switchStage(player, session);
                } else {
                    finish(player);
                    controller.submitLogin(player, value, "");
                }
            }
            case LOGIN_TOTP -> {
                var password = session.firstValue;
                finish(player);
                controller.submitLogin(player, password, value);
            }
            case REGISTER_PASSWORD -> {
                session.firstValue = value;
                session.input = "";
                session.stage = Stage.REGISTER_CONFIRM;
                switchStage(player, session);
            }
            case REGISTER_CONFIRM -> {
                var password = session.firstValue;
                finish(player);
                controller.submitRegistration(player, password, value);
            }
        }
    }

    private void switchStage(Player player, Session session) {
        var user = packetUser(player);
        if (user != null) user.closeInventory();
        controller.runLater(
                () -> {
                    if (sessions.get(player.getUniqueId()) == session) {
                        openSession(player, session, false);
                    }
                },
                1L);
    }

    private void finish(Player player) {
        sessions.remove(player.getUniqueId());
        var user = packetUser(player);
        if (user != null) user.closeInventory();
    }

    private void refresh(Player player, Session session) {
        openSession(player, session, true);
    }

    private void openSession(Player player, Session session, boolean refresh) {
        if (!player.isOnline()) return;
        var user = packetUser(player);
        if (user == null) return;

        var registered = session.state.registered();
        var title =
                configuration.get(
                        registered
                                ? AUTHENTICATION_UI_LOGIN_TITLE
                                : AUTHENTICATION_UI_REGISTER_TITLE);
        var prompt = prompt(session);
        var submit =
                configuration.get(
                        registered
                                ? AUTHENTICATION_UI_LOGIN_BUTTON
                                : AUTHENTICATION_UI_REGISTER_BUTTON);

        var left =
                createItem(
                        ItemTypes.REDSTONE,
                        Component.empty(),
                        List.of(Component.text(controller.closeButtonText())));
        var right = createItem(ItemTypes.PAPER, Component.text(title), List.of(prompt));
        var output = createItem(ItemTypes.ARROW, Component.text(submit), List.of(prompt));

        if (!refresh) {
            user.sendPacket(
                    new WrapperPlayServerOpenWindow(
                            WINDOW_ID,
                            anvilWindowType,
                            Component.text(title).append(Component.text(" — ")).append(prompt)));
        }

        user.sendPacket(
                new WrapperPlayServerWindowItems(
                        WINDOW_ID, STATE_ID, Arrays.asList(left, right, output), ItemStack.EMPTY));
    }

    private Component prompt(Session session) {
        if (session.feedback != null && session.stage.isFirst()) return session.feedback;
        return Component.text(
                configuration.get(
                        switch (session.stage) {
                            case LOGIN_PASSWORD -> AUTHENTICATION_UI_LOGIN_TIP;
                            case LOGIN_TOTP -> AUTHENTICATION_UI_TOTP_TIP;
                            case REGISTER_PASSWORD -> AUTHENTICATION_UI_REGISTER_TIP;
                            case REGISTER_CONFIRM -> AUTHENTICATION_UI_CONFIRM_TIP;
                        }));
    }

    private ItemStack createItem(ItemType type, Component name, List<Component> loreLines) {
        var item = ItemStack.builder().type(type).amount(1).build();
        var cleanName = clean(name);
        var cleanLore = loreLines.stream().map(this::clean).toList();

        if (PacketEvents.getAPI()
                .getServerManager()
                .getVersion()
                .isNewerThanOrEquals(ServerVersion.V_1_20_5)) {
            item.setComponent(ComponentTypes.CUSTOM_NAME, cleanName);
            item.setComponent(ComponentTypes.LORE, new ItemLore(cleanLore));
            return item;
        }

        // 旧版还在吃 NBT。看着上古，但 ViaBackwards 真能把人送过来。
        NBTCompound root = item.getOrCreateTag();
        NBTCompound display = new NBTCompound();
        display.setTag("Name", new NBTString(GsonComponentSerializer.gson().serialize(cleanName)));
        NBTList<NBTString> lore = new NBTList<>(NBTType.STRING);
        for (Component line : cleanLore) {
            lore.addTag(new NBTString(GsonComponentSerializer.gson().serialize(line)));
        }
        display.setTag("Lore", lore);
        root.setTag("display", display);
        return item;
    }

    private Component clean(Component component) {
        return component
                .colorIfAbsent(NamedTextColor.WHITE)
                .decoration(TextDecoration.ITALIC, false);
    }

    private User packetUser(Player player) {
        return PacketEvents.getAPI().getPlayerManager().getUser(player);
    }

    private int resolveAnvilWindowType() {
        var version = PacketEvents.getAPI().getServerManager().getVersion();
        if (version.isNewerThanOrEquals(ServerVersion.V_26_1)) {
            try {
                Class<?> registries =
                        Class.forName("net.minecraft.core.registries.BuiltInRegistries");
                Field menuField = registries.getField("MENU");
                Object menuRegistry = menuField.get(null);
                Class<?> menuType = Class.forName("net.minecraft.world.inventory.MenuType");
                Object anvil = menuType.getField("ANVIL").get(null);
                Method getId = menuRegistry.getClass().getMethod("getId", Object.class);
                return (int) getId.invoke(menuRegistry, anvil);
            } catch (ReflectiveOperationException exception) {
                controller.logAnvilFallback(exception);
                return 8;
            }
        }
        return version.isNewerThanOrEquals(ServerVersion.V_1_20_3) ? 8 : 7;
    }

    private enum Stage {
        LOGIN_PASSWORD,
        LOGIN_TOTP,
        REGISTER_PASSWORD,
        REGISTER_CONFIRM;

        boolean isFirst() {
            return this == LOGIN_PASSWORD || this == REGISTER_PASSWORD;
        }
    }

    private static final class Session {
        private final AuthenticationUiState state;
        private final Component feedback;
        private Stage stage;
        private String input = "";
        private String firstValue = "";

        private Session(AuthenticationUiState state, Stage stage, Component feedback) {
            this.state = state;
            this.stage = stage;
            this.feedback = feedback;
        }
    }
}
