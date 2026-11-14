# Changelog

## [2.1.0](https://github.com/team581/spot/compare/camera-viewer-v2.0.1...camera-viewer-v2.1.0) (2026-11-14)


### Features

* **camera-viewer:** draw cameras with their 3D model ([6fb0b5c](https://github.com/team581/spot/commit/6fb0b5c3cbf04f0e9e7144143c558f506e2aea2b))
* **dashboard:** show camera images in the 3D field view ([7f9afb3](https://github.com/team581/spot/commit/7f9afb3a41d55d795498a13437395baaee2393f1))
* **dashboard:** undistort camera images in the 3D field view ([17ace1c](https://github.com/team581/spot/commit/17ace1c2e6993596ccefaf5d2c924901078832e6))

## [2.0.1](https://github.com/team581/spot/compare/camera-viewer-v2.0.0...camera-viewer-v2.0.1) (2026-11-13)


### Bug Fixes

* **vscode-camera-preview:** run release ([ef44a61](https://github.com/team581/spot/commit/ef44a61d1ce64036552c2027d4c10bc51a104e7b))

## [2.0.0](https://github.com/team581/spot/compare/camera-viewer-v1.1.1...camera-viewer-v2.0.0) (2026-11-13)


### ⚠ BREAKING CHANGES

* **dashboard:** @spot/camera-viewer's field mode takes `cameras` (each camera's mount, color, robot estimate, and used tags). The single-camera `geometry` and `data` state, `Candidate`, and `robotPose` are removed; use `cameras` and `compose`.

### Features

* **dashboard:** add a 3D field view and recording replay ([d9a67ec](https://github.com/team581/spot/commit/d9a67ec48bbb7d4ad0fda2ad606cbc8df7075b24))

## [1.1.1](https://github.com/team581/spot-2026/compare/camera-viewer-v1.1.0...camera-viewer-v1.1.1) (2026-11-10)


### Bug Fixes

* **camera-viewer:** keep live preview framing stable when tags flicker ([7e9313d](https://github.com/team581/spot-2026/commit/7e9313dd81bf67db857f57a664ab7e8eaababf0a))

## [1.1.0](https://github.com/team581/spot-2026/compare/camera-viewer-v1.0.0...camera-viewer-v1.1.0) (2026-11-07)


### Features

* **camera-viewer:** render geometry with Three.js and add WASD navigation ([03fdb19](https://github.com/team581/spot-2026/commit/03fdb19a7e30bc06d460453be0e1b09b9f28a5e9))

## 1.0.0 (2026-11-04)


### Features

* **vscode-camera-preview:** publish to VS Code Marketplace ([845517b](https://github.com/team581/spot-2026/commit/845517bb9c96ae2e9e84335a9b5a6255cb3bed11))
