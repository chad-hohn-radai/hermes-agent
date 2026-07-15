# nix/overlays.nix — Expose pkgs.hermes-agent for external NixOS configs
{ inputs, ... }:
{
  flake.overlays.default = final: _: {
    hermes-agent = final.callPackage ./hermes-agent.nix (
      import ./callHermesArgs.nix inputs
      // {
        npm-lockfile-fix = inputs.npm-lockfile-fix.packages.${final.stdenv.hostPlatform.system}.default;
      }
    );
  };
}
