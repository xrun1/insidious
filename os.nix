self: {config, lib, pkgs, ...}: let
    name = "insidious";
    displayName = "Insidious";
    cfg = config.services.${name}; 
in {
    options.services.${name} = {
        enable = lib.mkEnableOption false;
        package = lib.mkOption {
            type = with lib.types; nullOr package;
            description = ''The ${displayName} package to use.'';
            default = self.packages.${pkgs.system}.default;
        };
        address = lib.mkOption {
            type = with lib.types; str;
            description = "The IP address ${displayName} should bind to.";
            default = "127.0.0.1";
        };
        port = lib.mkOption {
            type = with lib.types; port;
            description = ''The port ${displayName} should listen on.'';
            default = 8000;
        };
        openFirewall = lib.mkOption {
            type = with lib.types; bool;
            description = "Open ports in the firewall for ${displayName}.";
            default = false;
        };
        user = lib.mkOption {
            type = with lib.types; str;
            default = name;
            description = "User account under which ${displayName} runs.";
        };
        group = lib.mkOption {
            type = with lib.types; str;
            default = name;
            description = "Group under which ${displayName} runs.";
        };
        home = lib.mkOption {
            type = with lib.types; path;
            default = "/var/lib/${name}";
            description = ''
              Directory where ${displayName} will keep its application data.
            '';
        };
    };

    config = lib.mkIf cfg.enable {
        systemd.services.${name} = rec {
            description = "${displayName} YouTube front-end";
            wantedBy = ["multi-user.target"];
            wants = ["network-online.target"];
            after = wants;
            script = ''
                ${lib.getExe cfg.package} ${cfg.address} ${toString cfg.port}
            '';
            serviceConfig = {
                User = cfg.user;
                Group = cfg.group;
                CapabilityBoundingSet = "";
                LockPersonality = true;
                MemoryDenyWriteExecute = true;
                NoNewPrivileges = true;
                PrivateDevices = true;
                PrivateMounts = true;
                PrivateTmp = true;
                PrivateUsers = true;
                ProtectClock = true;
                ProtectControlGroups = true;
                ProtectHome = true;
                ProtectHostname = true;
                ProtectKernelLogs = true;
                ProtectKernelModules = true;
                ProtectKernelTunables = true;
                ProtectProc = "invisible";
                ProtectSystem = "strict";
                ReadWritePaths = [cfg.home];
                RemoveIPC = true;
                RestrictAddressFamilies = ["AF_UNIX" "AF_INET" "AF_INET6"];
                RestrictNamespaces = true;
                RestrictRealtime = true;
                RestrictSUIDSGID = true;
                SystemCallArchitectures = "native";
                SystemCallFilter = [
                    "@system-service" "~@privileged" "~@resources"
                ];
            };
        };
        users.users = lib.optionalAttrs (cfg.user == name) ({
            ${name} = {
                group = cfg.group;
                description = "${displayName} runner user";
                home = cfg.home;
                createHome = true;
                isSystemUser = true;
            };
        });
        users.groups = lib.optionalAttrs (cfg.group == name) ({
            ${name} = {};
        });
        networking.firewall = lib.mkIf cfg.openFirewall rec {
            allowedTCPPorts = [cfg.port];
            allowedUDPPorts = allowedTCPPorts;
        };
    };
}
