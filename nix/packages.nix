{ inputs, pkgs }:
let
  inherit (pkgs) lib;
  opencv = pkgs.callPackage ./opencv.nix { };
  jetson = pkgs.stdenv.hostPlatform.isLinux && pkgs.stdenv.hostPlatform.isAarch64;
  source = lib.cleanSourceWith {
    src = ../.;
    filter =
      path: type:
      lib.cleanSourceFilter path type
      && !(builtins.elem (baseNameOf path) [
        ".git"
        "node_modules"
        "target"
        "build"
        "dist"
        ".astro"
        "test-results"
      ]);
  };
  webSource = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.intersection (lib.fileset.fromSource source) (
      lib.fileset.unions [
        ../package.json
        ../pnpm-lock.yaml
        ../pnpm-workspace.yaml
        ../vite.config.ts
        ../apps/dashboard
        ../apps/docs
        ../apps/vscode-camera-preview/package.json
        ../packages/camera-viewer
      ]
    );
  };
  # Reuse pnpm's integrity hashes without a store hash or builds during evaluation.
  # TODO: Revisit this dependency's custom YAML parser when Nixpkgs supports
  # pnpm imports without a separate store hash.
  pnpm2nix = pkgs.callPackage "${inputs.pnpm2nix}/nix/lockfile.nix" { };
  # pnpm skips packages for other platforms, so only fetch the build platform's.
  supports =
    field: value: package:
    let
      values = package.${field} or [ ];
    in
    values == [ ]
    || builtins.elem value values
    || (lib.all (lib.hasPrefix "!") values && !builtins.elem "!${value}" values);
  supported =
    package:
    let
      platform = pkgs.stdenv.buildPlatform;
    in
    supports "os" platform.node.platform package
    && supports "cpu" platform.node.arch package
    && supports "libc" (if platform.isMusl then "musl" else "glibc") package;
  fetchPackage =
    key: package:
    let
      source = pnpm2nix.resolveSource "https://registry.npmjs.org" key package;
    in
    assert lib.assertMsg (source.type == "url") "pnpm: unsupported source for ${key}";
    {
      tarball = "file:${pkgs.fetchurl { inherit (source) url hash; }}";
      integrity = source.hash;
    };
  pnpmLockfile = pkgs.writeText "pnpm-lock.yaml" (
    lib.concatMapStrings (
      document:
      "---\n"
      + builtins.toJSON (
        document
        // {
          lockfileVersion = "9.0";
          packages = lib.mapAttrs (
            key: package:
            package // lib.optionalAttrs (supported package) { resolution = fetchPackage key package; }
          ) (document.packages or { });
        }
      )
      + "\n"
    ) (pnpm2nix.parseLockfile { lockfile = ../pnpm-lock.yaml; })
  );
  web = pkgs.stdenvNoCC.mkDerivation {
    pname = "spot-web";
    version = "2026.2.1"; # x-release-please-version
    src = webSource;
    nativeBuildInputs = [
      pkgs.nodejs
      pkgs.pnpm
    ];
    configurePhase = ''
      runHook preConfigure
      export HOME="$TMPDIR"
      export pnpm_config_pm_on_fail=ignore
      export pnpm_config_store_dir="$TMPDIR/pnpm-store"
      cp ${pnpmLockfile} pnpm-lock.yaml
      pnpm --filter spot --filter spot-dashboard... --filter spot-docs... install \
        --offline --frozen-lockfile --ignore-scripts --trust-lockfile
      patchShebangs node_modules/{*,.*}
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      pnpm --filter spot-dashboard build
      pnpm build:jetson
      runHook postBuild
    '';
    installPhase = ''
      mkdir -p $out
      cp -r dist/dashboard dist/jetson-docs $out/
    '';
  };
  # nvcc needs the host compiler that CUDA supports.
  craneLib = (inputs.crane.mkLib pkgs).overrideScope (
    _: _: {
      stdenvSelector = p: if jetson then p.cudaPackages.backendStdenv else p.stdenv;
    }
  );
  rustArgs = {
    pname = "spot-vision";
    version = "2026.2.1"; # x-release-please-version
    src = lib.fileset.toSource {
      root = ../apps/vision;
      fileset = lib.fileset.intersection (lib.fileset.fromSource source) (
        lib.fileset.unions [
          ../apps/vision/Cargo.toml
          ../apps/vision/Cargo.lock
          ../apps/vision/build.rs
          ../apps/vision/src
          ../apps/vision/cpp
          ../apps/vision/tests
        ]
      );
    };
    cargoExtraArgs = lib.concatStringsSep " " (
      [ "--locked" ] ++ lib.optionals jetson [ "--features jetson" ]
    );
    nativeBuildInputs = [
      pkgs.rustPlatform.bindgenHook
      pkgs.pkg-config
    ]
    ++ lib.optionals jetson [
      pkgs.cudaPackages.cuda_nvcc
      pkgs.autoAddDriverRunpath
    ];
    buildInputs = [
      opencv
    ]
    ++ lib.optionals jetson [
      pkgs.cudaPackages.cuda_cudart
      pkgs.cudaPackages.cuda_cccl
    ];
    # CI runs the tests; Jetson tests would also need the GPU.
    doCheck = false;
  };
  spot = craneLib.buildPackage (
    rustArgs
    // {
      # Dependencies build separately, so changing Spot's source reuses them.
      cargoArtifacts = craneLib.buildDepsOnly rustArgs;
      meta.mainProgram = "spot-vision";
    }
  );
in
{
  inherit spot web opencv;
}
