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
  web = pkgs.stdenvNoCC.mkDerivation (finalAttrs: {
    pname = "spot-web";
    version = "0.2.1";
    src = webSource;
    nativeBuildInputs = [
      pkgs.nodejs
      pkgs.pnpm
      pkgs.pnpmConfigHook
    ];
    pnpmWorkspaces = [
      "spot"
      "spot-dashboard..."
      "spot-docs..."
    ];
    pnpmDeps = pkgs.fetchPnpmDeps {
      inherit (finalAttrs) version src pnpmWorkspaces;
      # A changed lockfile must fetch fresh dependencies even while the old hash is pinned.
      pname = "${finalAttrs.pname}-${
        builtins.hashString "sha256" (
          builtins.readFile ../pnpm-lock.yaml
          + builtins.readFile ../pnpm-workspace.yaml
          + builtins.readFile ../flake.lock
        )
      }";
      fetcherVersion = 5;
      hash = "sha256-xhjfqA2yKtN89+eS0kHJRJ3e+DFjdhqc1jRr/+aKjSU=";
    };
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
  });
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
                ];
              dontUseCmakeConfigure = true;
              env = (old.env or { }) // {
                CMAKE_BUILD_PARALLEL_LEVEL = "2";
                CMAKE_ARGS = lib.concatStringsSep " " [
                  "-DSPOT_BUILD_CUDA=${if cuda then "ON" else "OFF"}"
                  "-DSPOT_CUDA_ARCHITECTURES=87"
                  "-Dpybind11_DIR=${final.pythonPkgsBuildHost.pybind11}/${pkgs.python312.sitePackages}/pybind11/share/cmake/pybind11"
                  "-DSPOT_DASHBOARD_DIR=${web}/dashboard"
                  "-DSPOT_DOCS_DIR=${web}/jetson-docs"
                ];
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
