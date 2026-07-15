# nix/callHermesArgs.nix — Shared callPackage arguments for hermes-agent.nix
#
# packages.nix (perSystem) and overlays.nix (overlay) both call
# ./hermes-agent.nix with the same flake-input wiring.  This file is that
# single set of args — import it and spread, adding only the
# system-resolved npm-lockfile-fix package at each call site.
#
# Only embed clean revs — dirtyRev doesn't represent any upstream commit,
# so comparing it would always claim "update available".
inputs: {
  inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
  rev = inputs.self.rev or null;
}
