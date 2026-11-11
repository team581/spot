//! HTTP API and static dashboard/docs hosting.

use std::path::Path as FsPath;
use std::sync::Arc;

use axum::Json;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use serde_json::{Map, Value};
use tower_http::services::{ServeDir, ServeFile};
use utoipa::OpenApi;
use utoipa_axum::router::OpenApiRouter;
use utoipa_axum::routes;

use crate::app::{App, CalibrationView, ConfigView, DeviceStatus, Settings, Status};
use crate::network::{self, NetworkChange, NetworkStatus, Request};
use crate::recording::Recording;
use crate::system::SystemStatus;

type AppState = State<Arc<App>>;

#[derive(OpenApi)]
#[openapi(info(title = "Spot", description = "Spot vision service API"))]
struct Api;

fn router() -> OpenApiRouter<Arc<App>> {
    OpenApiRouter::with_openapi(Api::openapi())
        .routes(routes!(status))
        .routes(routes!(devices))
        .routes(routes!(config))
        .routes(routes!(set_overrides))
        .routes(routes!(settings, set_settings))
        .routes(routes!(recordings))
        .routes(routes!(system))
        .routes(routes!(board))
        .routes(routes!(calibration, start_calibration, stop_calibration))
        .routes(routes!(capture_calibration))
        .routes(routes!(solve_calibration))
        .routes(routes!(network_status, apply_network))
        .routes(routes!(confirm_network))
        .routes(routes!(revert_network))
}

pub fn openapi() -> utoipa::openapi::OpenApi {
    router().split_for_parts().1
}

pub fn app(app: Arc<App>, web: Option<&FsPath>, docs: Option<&FsPath>) -> axum::Router {
    let (api, spec) = router().split_for_parts();
    let recordings = ServeDir::new(app.recorder().dir());
    let mut router = api
        .nest_service("/recordings", recordings)
        .route("/api/openapi.json", axum::routing::get(move || async move { Json(spec) }))
        .with_state(app);
    if let Some(docs) = docs {
        router = router.nest_service("/docs", ServeDir::new(docs));
    }
    if let Some(web) = web {
        // Client-side routes fall back to the dashboard's entry point.
        router = router
            .fallback_service(ServeDir::new(web).fallback(ServeFile::new(web.join("index.html"))));
    }
    router
}

/// Spot and camera status.
#[utoipa::path(get, path = "/api/status", responses((status = 200, body = Status)))]
async fn status(State(app): AppState) -> Json<Status> {
    Json(app.status())
}

/// Cameras plugged into Spot, whether or not they are configured.
#[utoipa::path(get, path = "/api/devices", responses((status = 200, body = Vec<DeviceStatus>)))]
async fn devices(State(app): AppState) -> Json<Vec<DeviceStatus>> {
    Json(app.devices())
}

/// Robot config, dashboard overrides, and the merged result.
#[utoipa::path(get, path = "/api/config", responses((status = 200, body = ConfigView)))]
async fn config(State(app): AppState) -> Json<ConfigView> {
    Json(app.config())
}

/// Replaces the dashboard overrides.
#[utoipa::path(
    put,
    path = "/api/config/overrides",
    request_body(content = std::collections::HashMap<String, serde_json::Value>, description = "Deep-partial config; null removes a key"),
    responses((status = 200, body = ConfigView), (status = 422, body = String, description = "The merged config is invalid")),
)]
async fn set_overrides(
    State(app): AppState,
    Json(overrides): Json<Map<String, Value>>,
) -> Result<Json<ConfigView>, (StatusCode, String)> {
    app.set_overrides(overrides).map(Json).map_err(|e| (StatusCode::UNPROCESSABLE_ENTITY, e))
}

/// Jetson-local settings.
#[utoipa::path(get, path = "/api/settings", responses((status = 200, body = Settings)))]
async fn settings(State(app): AppState) -> Json<Settings> {
    Json(app.settings())
}

#[utoipa::path(put, path = "/api/settings", request_body = Settings, responses((status = 200, body = Settings)))]
async fn set_settings(State(app): AppState, Json(settings): Json<Settings>) -> Json<Settings> {
    app.set_settings(settings);
    Json(app.settings())
}

/// Saved MCAP recordings, newest first. Download them from `/recordings/<name>`.
#[utoipa::path(get, path = "/api/recordings", responses((status = 200, body = Vec<Recording>)))]
async fn recordings(State(app): AppState) -> Json<Vec<Recording>> {
    Json(app.recorder().recordings())
}

/// CPU, memory, GPU, disk, and temperatures.
#[utoipa::path(get, path = "/api/system", responses((status = 200, body = SystemStatus)))]
async fn system(State(app): AppState) -> Json<SystemStatus> {
    Json(app.system())
}

type NetworkReply = Result<Json<NetworkStatus>, (StatusCode, String)>;

async fn network(request: Request) -> NetworkReply {
    network::request(&request).await.map(Json).map_err(|e| (StatusCode::CONFLICT, e))
}

/// Ethernet addressing.
#[utoipa::path(get, path = "/api/network", responses((status = 200, body = NetworkStatus), (status = 409, body = String)))]
async fn network_status() -> NetworkReply {
    network(Request::Status).await
}

/// Tries new Ethernet addressing. It rolls back unless confirmed within 90 seconds.
#[utoipa::path(post, path = "/api/network", request_body = NetworkChange, responses((status = 200, body = NetworkStatus), (status = 409, body = String)))]
async fn apply_network(Json(change): Json<NetworkChange>) -> NetworkReply {
    network(Request::Apply(change)).await
}

/// Keeps the pending Ethernet change.
#[utoipa::path(post, path = "/api/network/confirm", responses((status = 200, body = NetworkStatus), (status = 409, body = String)))]
async fn confirm_network() -> NetworkReply {
    network(Request::Confirm).await
}

/// Rolls back the pending Ethernet change.
#[utoipa::path(post, path = "/api/network/revert", responses((status = 200, body = NetworkStatus), (status = 409, body = String)))]
async fn revert_network() -> NetworkReply {
    network(Request::Revert).await
}

type CalibrationReply = Result<Json<CalibrationView>, (StatusCode, String)>;

fn conflict(error: String) -> (StatusCode, String) {
    (StatusCode::CONFLICT, error)
}

/// The configured ChArUco board as a printable, true-size SVG.
#[utoipa::path(get, path = "/api/calibration/board.svg", responses((status = 200, content_type = "image/svg+xml", body = String)))]
async fn board(
    State(app): AppState,
) -> Result<impl axum::response::IntoResponse, (StatusCode, String)> {
    let svg = app.board_svg().map_err(conflict)?;
    Ok(([(axum::http::header::CONTENT_TYPE, "image/svg+xml")], svg))
}

/// The camera's calibration session.
#[utoipa::path(get, path = "/api/calibration/{camera}", params(("camera" = String, Path)), responses((status = 200, body = CalibrationView), (status = 409, body = String)))]
async fn calibration(State(app): AppState, Path(camera): Path<String>) -> CalibrationReply {
    app.calibration(&camera).map(Json).map_err(conflict)
}

/// Starts calibrating a camera with the configured board, discarding any earlier session.
#[utoipa::path(post, path = "/api/calibration/{camera}", params(("camera" = String, Path)), responses((status = 200, body = CalibrationView), (status = 409, body = String)))]
async fn start_calibration(State(app): AppState, Path(camera): Path<String>) -> CalibrationReply {
    app.start_calibration(&camera).map(Json).map_err(conflict)
}

/// Ends a calibration session.
#[utoipa::path(delete, path = "/api/calibration/{camera}", params(("camera" = String, Path)), responses((status = 204)))]
async fn stop_calibration(State(app): AppState, Path(camera): Path<String>) -> StatusCode {
    app.stop_calibration(&camera);
    StatusCode::NO_CONTENT
}

/// Keeps the board corners visible in the latest frame.
#[utoipa::path(post, path = "/api/calibration/{camera}/capture", params(("camera" = String, Path)), responses((status = 200, body = CalibrationView), (status = 409, body = String)))]
async fn capture_calibration(State(app): AppState, Path(camera): Path<String>) -> CalibrationReply {
    app.capture_calibration(&camera).map(Json).map_err(conflict)
}

/// Solves for intrinsics from the captured views. Apply the result as an override.
#[utoipa::path(post, path = "/api/calibration/{camera}/solve", params(("camera" = String, Path)), responses((status = 200, body = CalibrationView), (status = 409, body = String)))]
async fn solve_calibration(State(app): AppState, Path(camera): Path<String>) -> CalibrationReply {
    tokio::task::spawn_blocking(move || app.solve_calibration(&camera))
        .await
        .map_err(|e| conflict(e.to_string()))?
        .map(Json)
        .map_err(conflict)
}
