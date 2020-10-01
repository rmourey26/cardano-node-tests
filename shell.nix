let
  sources = import ./nix/sources.nix {};
  pkgs = import sources.nixpkgs {};
  cardano-address = (import sources.cardano-wallet {}).haskellPackages.cardano-addresses.components.exes.cardano-address;
  shell = (import (sources.cardano-node + "/shell.nix") {}).devops.overrideAttrs (oldAttrs: {
    buildInputs = oldAttrs.buildInputs ++ (with pkgs.python3Packages; [
      pytest
      pytest-html
      pytest-ordering
      pytest_xdist
      setuptools
      filelock
      pylint
      mypy
      hypothesis
      cardano-address
    ]);
  });

in shell
