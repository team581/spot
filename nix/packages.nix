{ inputs, pkgs }:
let
  inherit (pkgs) lib;
  inherit (inputs)
    self
    uv2nix
    pyproject-nix
    pyproject-build-systems
    ;
  cuda = pkgs.stdenv.hostPlatform.isLinux && pkgs.stdenv.hostPlatform.isAarch64;
  # Headers and decoder classes for the NVJPG engine (Jetson Multimedia API).
  jetsonMultimediaApi =
    pkgs.runCommand "jetson-multimedia-api" { nativeBuildInputs = [ pkgs.dpkg ]; }
      ''
        dpkg -x ${pkgs.nvidia-jetpack.debs.common.nvidia-l4t-jetson-multimedia-api.src} source
        mv source/usr/src/jetson_multimedia_api $out
      '';
  source = lib.cleanSourceWith {
    src = ../.;
    filter =
      path: type:
      lib.cleanSourceFilter path type
      && !(builtins.elem (baseNameOf path) [
        ".git"
        ".venv"
        "node_modules"
        "build"
        "dist"
        ".astro"
        "__pycache__"
        "test-results"
        ".pytest_cache"
        ".ruff_cache"
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
  visionSource = lib.fileset.toSource {
    root = ../apps/vision;
    fileset = lib.fileset.intersection (lib.fileset.fromSource source) (
      lib.fileset.unions [
        ../apps/vision/pyproject.toml
        ../apps/vision/README.md
        ../apps/vision/CMakeLists.txt
        ../apps/vision/cpp
        ../apps/vision/src
      ]
    );
  };
  # Reuse pnpm's integrity hashes without a store hash or builds during evaluation.
  # TODO: Revisit this dependency's custom YAML parser when Nixpkgs supports
  # pnpm imports without a separate store hash.
  pnpmLockfile = (pkgs.callPackage "${inputs.pnpm2nix}/nix/lockfile.nix" { }).processLockfile {
    lockfile = ../pnpm-lock.yaml;
    registry = "https://registry.npmjs.org";
    noDevDependencies = false;
    lockfileResolver = "regex";
  };
  web = pkgs.stdenvNoCC.mkDerivation {
    pname = "spot-web";
    version = "0.2.1";
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
      cp ${pnpmLockfile.patchedLockfileYaml} pnpm-lock.yaml
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
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = self; };
  pythonSet =
    (pkgs.callPackage pyproject-nix.build.packages {
      python = pkgs.python312;
      stdenv = if cuda then pkgs.cudaPackages.backendStdenv else pkgs.stdenv;
    }).overrideScope
      (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
          # RobotPy splits shared libraries across wheels under native/*/lib.
          # Tell autoPatchelf where those dependencies live on NixOS.
          (
            final: prev:
            lib.mapAttrs
              (
                name: libraries:
                prev.${name}.overrideAttrs (
                  old:
                  lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
                    buildInputs =
                      (old.buildInputs or [ ]) ++ map (library: final."robotpy-native-${library}") libraries;
                    preFixup =
                      (old.preFixup or "")
                      + lib.concatMapStringsSep "\n" (
                        library:
                        ''addAutoPatchelfSearchPath "${
                          final."robotpy-native-${library}"
                        }/${pkgs.python312.sitePackages}/native/${library}/lib"''
                      ) libraries;
                  }
                )
              )
              {
                robotpy-native-wpinet = [ "wpiutil" ];
                robotpy-native-wpimath = [ "wpiutil" ];
                robotpy-native-ntcore = [
                  "wpiutil"
                  "wpinet"
                ];
                robotpy-wpiutil = [ "wpiutil" ];
                robotpy-wpinet = [
                  "wpiutil"
                  "wpinet"
                ];
                robotpy-wpimath = [
                  "wpiutil"
                  "wpimath"
                ];
                pyntcore = [
                  "wpiutil"
                  "wpinet"
                  "ntcore"
                ];
              }
          )
          (final: prev: {
            spot-vision = prev.spot-vision.overrideAttrs (old: {
              src = visionSource;
              nativeBuildInputs =
                (old.nativeBuildInputs or [ ])
                ++ [
                  pkgs.cmake
                  pkgs.ninja
                ]
                ++ final.resolveBuildSystem {
                  scikit-build-core = [ ];
                  pybind11 = [ ];
                };
              buildInputs =
                (old.buildInputs or [ ])
                ++ lib.optionals cuda [
                  pkgs.cudaPackages.cuda_nvcc
                  pkgs.cudaPackages.cuda_cccl
                  pkgs.cudaPackages.cuda_cudart
                  pkgs.gflags
                  pkgs.glog
                  pkgs.nvidia-jetpack.l4t-cuda
                  pkgs.nvidia-jetpack.l4t-multimedia
                ];
              dontUseCmakeConfigure = true;
              env = (old.env or { }) // {
                CMAKE_BUILD_PARALLEL_LEVEL = "2";
                CMAKE_ARGS =
                  lib.concatStringsSep " " [
                    "-DSPOT_BUILD_CUDA=${if cuda then "ON" else "OFF"}"
                    "-DSPOT_CUDA_ARCHITECTURES=87"
                    "-DSPOT_BUILD_NVJPG=${if cuda then "ON" else "OFF"}"
                    "-Dpybind11_DIR=${final.pythonPkgsBuildHost.pybind11}/${pkgs.python312.sitePackages}/pybind11/share/cmake/pybind11"
                    "-DSPOT_DASHBOARD_DIR=${web}/dashboard"
                    "-DSPOT_DOCS_DIR=${web}/jetson-docs"
                  ]
                  + lib.optionalString cuda (
                    " -DSPOT_JETSON_MULTIMEDIA_API=${jetsonMultimediaApi}"
                    + " -DSPOT_NVJPG_LIBRARY_DIRS=${pkgs.nvidia-jetpack.l4t-multimedia}/lib;${pkgs.nvidia-jetpack.l4t-cuda}/lib"
                  );
              };
            });
            sdnotify = prev.sdnotify.overrideAttrs (old: {
              nativeBuildInputs =
                (old.nativeBuildInputs or [ ]) ++ final.resolveBuildSystem { setuptools = [ ]; };
            });
          })
        ]
      );
  spot = pythonSet.mkVirtualEnv "spot-vision" {
    spot-vision = [
      "nt"
      "systemd"
    ];
  };
in
{
  inherit spot web;
}
