/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

package xyz.kyngs.librelogin.paper.ui;

import static xyz.kyngs.librelogin.common.config.ConfigurationKeys.*;

import com.github.retrooper.packetevents.PacketEvents;
import com.github.retrooper.packetevents.event.PacketListener;
import com.github.retrooper.packetevents.event.PacketListenerCommon;
import com.github.retrooper.packetevents.event.PacketListenerPriority;
import com.github.retrooper.packetevents.event.PacketReceiveEvent;
import com.github.retrooper.packetevents.protocol.player.ClientVersion;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;
import net.kyori.adventure.text.Component;
import org.bukkit.Bukkit;
import org.bukkit.World;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.HandlerList;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerRespawnEvent;
import xyz.kyngs.librelogin.api.event.events.AuthenticatedEvent;
import xyz.kyngs.librelogin.common.AuthenticLibreLogin;
import xyz.kyngs.librelogin.common.command.InvalidCommandArgument;
import xyz.kyngs.librelogin.common.command.commands.authorization.LoginCommand;
import xyz.kyngs.librelogin.common.command.commands.authorization.RegisterCommand;
import xyz.kyngs.librelogin.common.config.key.ConfigurationKey;
import xyz.kyngs.librelogin.common.ui.AuthenticationUiMode;
import xyz.kyngs.librelogin.common.ui.AuthenticationUiState;
import xyz.kyngs.librelogin.common.util.GeneralUtil;
import xyz.kyngs.librelogin.paper.PaperLibreLogin;

/** 只管“怎么把登录页摆到玩家脸上”，认证、限次、哈希、传送全都继续走 LibreLogin 原来的逻辑。 这条边界不能糊，不然后面修认证漏洞时能把 UI 一起修成烟花。 */
public final class AuthenticationUiController implements PacketListener, Listener {

    private final PaperLibreLogin plugin;
    private final LoginCommand<Player> loginCommand;
    private final RegisterCommand<Player> registerCommand;
    private final DialogAuthenticationView dialogView;
    private final AnvilAuthenticationView anvilView;
    private final Map<UUID, AuthenticationUiState> states = new ConcurrentHashMap<>();
    private final Set<UUID> loading = ConcurrentHashMap.newKeySet();
    private final Set<UUID> submitting = ConcurrentHashMap.newKeySet();

    private PacketListenerCommon packetRegistration;
    private Consumer<AuthenticatedEvent<Player, World>> authenticatedHandler;

    public AuthenticationUiController(PaperLibreLogin plugin) {
        this.plugin = plugin;
        this.loginCommand = new LoginCommand<>(plugin);
        this.registerCommand = new RegisterCommand<>(plugin);
        this.dialogView = new DialogAuthenticationView(this, plugin.getConfiguration());
        this.anvilView = new AnvilAuthenticationView(this, plugin.getConfiguration());
    }

    public void enable() {
        Bukkit.getPluginManager().registerEvents(this, plugin.getBootstrap());
        packetRegistration =
                PacketEvents.getAPI()
                        .getEventManager()
                        .registerListener(this, PacketListenerPriority.NORMAL);
        authenticatedHandler =
                plugin.getEventProvider()
                        .subscribe(
                                plugin.getEventTypes().authenticated,
                                event -> runSync(() -> authenticated(event.getPlayer())));
        plugin.getLogger().info("图形化登录界面接上了，原生对话框和铁砧兜底都能用。");
    }

    public void disable() {
        HandlerList.unregisterAll(this);
        if (authenticatedHandler != null) {
            plugin.getEventProvider().unsubscribe(authenticatedHandler);
            authenticatedHandler = null;
        }
        if (packetRegistration != null) {
            PacketEvents.getAPI().getEventManager().unregisterListener(packetRegistration);
            packetRegistration = null;
        }
        anvilView.clear();
        states.clear();
        loading.clear();
        submitting.clear();
    }

    @Override
    public void onPacketReceive(PacketReceiveEvent event) {
        if (dialogView.handle(event)) return;
        anvilView.handle(event);
    }

    @EventHandler(priority = EventPriority.NORMAL)
    public void onJoin(PlayerJoinEvent event) {
        var ticks = Math.max(1, plugin.getConfiguration().get(AUTHENTICATION_UI_DELAY_TICKS));
        runLater(() -> show(event.getPlayer(), null), ticks);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onRespawn(PlayerRespawnEvent event) {
        runLater(() -> show(event.getPlayer(), null), 1L);
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        var player = event.getPlayer();
        var uuid = player.getUniqueId();
        states.remove(uuid);
        loading.remove(uuid);
        submitting.remove(uuid);
        anvilView.forget(player);
    }

    void submitLogin(Player player, String password, String totp) {
        if (password == null || password.isBlank()) {
            showFeedback(player, AUTHENTICATION_UI_EMPTY_INPUT);
            return;
        }
        if (!submitting.add(player.getUniqueId())) {
            showFeedback(player, AUTHENTICATION_UI_BUSY);
            return;
        }

        loginCommand
                .onLogin(player, player, password, totp == null || totp.isBlank() ? null : totp)
                .whenComplete(
                        (ignored, throwable) -> {
                            submitting.remove(player.getUniqueId());
                            if (throwable != null) {
                                handleSubmissionFailure(
                                        player, throwable, AUTHENTICATION_UI_LOGIN_FAILED);
                            }
                        });
    }

    void submitRegistration(Player player, String password, String confirm) {
        if (password == null || password.isBlank() || confirm == null || confirm.isBlank()) {
            showFeedback(player, AUTHENTICATION_UI_EMPTY_INPUT);
            return;
        }
        if (!submitting.add(player.getUniqueId())) {
            showFeedback(player, AUTHENTICATION_UI_BUSY);
            return;
        }

        registerCommand
                .onRegister(player, player, password, confirm)
                .whenComplete(
                        (ignored, throwable) -> {
                            submitting.remove(player.getUniqueId());
                            if (throwable != null) {
                                handleSubmissionFailure(
                                        player, throwable, AUTHENTICATION_UI_REGISTER_FAILED);
                            }
                        });
    }

    void handleClose(Player player) {
        anvilView.forget(player);
        if (plugin.getConfiguration().get(AUTHENTICATION_UI_ALLOW_CLOSE)) {
            player.sendMessage(
                    Component.text(
                            plugin.getConfiguration().get(AUTHENTICATION_UI_CLOSED_MESSAGE)));
            return;
        }
        runSync(
                () ->
                        player.kick(
                                Component.text(
                                        plugin.getConfiguration()
                                                .get(AUTHENTICATION_UI_EXIT_MESSAGE))));
    }

    void showInternalError(Player player) {
        var message =
                Component.text(plugin.getConfiguration().get(AUTHENTICATION_UI_INTERNAL_ERROR));
        var state = states.get(player.getUniqueId());
        if (state == null) {
            // 数据库自己都翻车了，再查一遍只会原地套娃，直接把话说明白得了。
            player.sendMessage(message);
            return;
        }
        open(player, state, message);
    }

    String closeButtonText() {
        return plugin.getConfiguration()
                .get(
                        plugin.getConfiguration().get(AUTHENTICATION_UI_ALLOW_CLOSE)
                                ? AUTHENTICATION_UI_CLOSE_BUTTON
                                : AUTHENTICATION_UI_EXIT_BUTTON);
    }

    void runLater(Runnable runnable, long ticks) {
        Bukkit.getScheduler().runTaskLater(plugin.getBootstrap(), runnable, ticks);
    }

    void logAnvilFallback(Exception exception) {
        plugin.getLogger().warn("新版本铁砧菜单编号读取失败，这次先使用兼容编号 8。", exception);
    }

    private void show(Player player, Component feedback) {
        if (!player.isOnline() || !uiEnabled() || alreadyDone(player)) return;
        var cached = states.get(player.getUniqueId());
        if (cached != null) {
            open(player, cached, feedback);
            return;
        }

        if (!loading.add(player.getUniqueId())) return;
        AuthenticLibreLogin.EXECUTOR.execute(
                () -> {
                    try {
                        var user = plugin.getDatabaseProvider().getByUUID(player.getUniqueId());
                        if (user == null) {
                            plugin.getLogger()
                                    .warn("准备给 %s 打开登录页，但数据库里没有对应账号。".formatted(player.getName()));
                            return;
                        }
                        var state =
                                new AuthenticationUiState(
                                        user.isRegistered(),
                                        user.getSecret() != null
                                                && plugin.getTOTPProvider() != null);
                        states.put(player.getUniqueId(), state);
                        runSync(() -> open(player, state, feedback));
                    } catch (Throwable throwable) {
                        plugin.getLogger()
                                .error("给 %s 准备登录界面时出了问题。".formatted(player.getName()), throwable);
                        runSync(() -> showInternalError(player));
                    } finally {
                        loading.remove(player.getUniqueId());
                    }
                });
    }

    private void open(Player player, AuthenticationUiState state, Component feedback) {
        if (!player.isOnline() || alreadyDone(player)) return;
        var packetUser = PacketEvents.getAPI().getPlayerManager().getUser(player);
        if (packetUser == null) {
            plugin.getLogger().warn("%s 的数据包连接没找着，登录页这次弹不出来。".formatted(player.getName()));
            return;
        }

        var clientSupportsDialog =
                packetUser.getClientVersion().isNewerThanOrEquals(ClientVersion.V_1_21_6);
        var mode =
                AuthenticationUiMode.choose(
                        uiEnabled(),
                        plugin.getConfiguration().get(AUTHENTICATION_UI_DIALOG_ENABLED),
                        plugin.getConfiguration().get(AUTHENTICATION_UI_ANVIL_ENABLED),
                        clientSupportsDialog);

        switch (mode) {
            case DIALOG -> {
                anvilView.forget(player);
                dialogView.open(player, state, feedback);
            }
            case ANVIL -> anvilView.open(player, state, feedback);
            case CHAT -> {
                // 聊天提示本来就在跑，这里别再重复发一遍。
            }
        }
    }

    private void handleSubmissionFailure(
            Player player, Throwable throwable, ConfigurationKey<String> messageKey) {
        var root = GeneralUtil.getFurthestCause(throwable);
        if (!(root instanceof InvalidCommandArgument)) {
            plugin.getLogger()
                    .error("%s 提交登录界面后，认证流程没有正常完成。".formatted(player.getName()), throwable);
            messageKey = AUTHENTICATION_UI_INTERNAL_ERROR;
        }
        var finalMessageKey = messageKey;
        runSync(() -> showFeedback(player, finalMessageKey));
    }

    private void showFeedback(Player player, ConfigurationKey<String> messageKey) {
        show(player, Component.text(plugin.getConfiguration().get(messageKey)));
    }

    private boolean uiEnabled() {
        return plugin.getConfiguration().get(AUTHENTICATION_UI_ENABLED);
    }

    private boolean alreadyDone(Player player) {
        return plugin.getAuthorizationProvider().isAuthorized(player)
                || plugin.getAuthorizationProvider().isAwaiting2FA(player);
    }

    private void authenticated(Player player) {
        if (player == null) return;
        states.remove(player.getUniqueId());
        loading.remove(player.getUniqueId());
        submitting.remove(player.getUniqueId());
        dialogView.close(player);
        anvilView.close(player);
    }

    private void runSync(Runnable runnable) {
        if (Bukkit.isPrimaryThread()) runnable.run();
        else Bukkit.getScheduler().runTask(plugin.getBootstrap(), runnable);
    }
}
