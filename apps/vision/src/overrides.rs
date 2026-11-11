//! Dashboard overrides: a deep-partial JSON object layered onto the robot's TOML.
//! Objects merge key by key, `null` removes a key, and any other value replaces it.

use serde_json::{Map, Value};
use toml_edit::{DocumentMut, InlineTable, Item};

/// Applies overrides to robot TOML, preserving the robot file's comments and formatting.
pub fn merge(robot_toml: &str, overrides: &Map<String, Value>) -> Result<String, String> {
    let mut document: DocumentMut = robot_toml.parse().map_err(|e| format!("robot config: {e}"))?;
    apply(document.as_item_mut(), overrides, "")?;
    Ok(document.to_string())
}

fn apply(item: &mut Item, patch: &Map<String, Value>, path: &str) -> Result<(), String> {
    let inline = item.is_inline_table();
    let table = item.as_table_like_mut().expect("overrides apply to tables");
    for (key, value) in patch {
        let at = if path.is_empty() { key.clone() } else { format!("{path}.{key}") };
        match value {
            Value::Null => {
                table.remove(key);
            }
            Value::Object(object) => {
                if !table.get(key).is_some_and(Item::is_table_like) {
                    let child = if inline {
                        Item::Value(InlineTable::new().into())
                    } else {
                        let mut child = toml_edit::Table::new();
                        child.set_implicit(true);
                        Item::Table(child)
                    };
                    table.insert(key, child);
                }
                apply(table.get_mut(key).unwrap(), object, &at)?;
            }
            value => {
                table.insert(key, Item::Value(to_toml(value, &at)?));
            }
        }
    }
    Ok(())
}

fn to_toml(value: &Value, at: &str) -> Result<toml_edit::Value, String> {
    Ok(match value {
        Value::Bool(b) => (*b).into(),
        Value::Number(n) => match n.as_i64() {
            Some(i) => i.into(),
            None => n.as_f64().ok_or_else(|| format!("{at}: number out of range"))?.into(),
        },
        Value::String(s) => s.as_str().into(),
        Value::Array(values) => {
            let mut array = toml_edit::Array::new();
            for v in values {
                array.push(to_toml(v, at)?);
            }
            array.into()
        }
        Value::Object(object) => {
            let mut table = InlineTable::new();
            for (k, v) in object {
                if !v.is_null() {
                    table.insert(k, to_toml(v, at)?);
                }
            }
            table.into()
        }
        Value::Null => unreachable!("null removes keys"),
    })
}

/// Removes overrides that the robot config already matches, and empty objects left behind.
pub fn prune(robot: &Map<String, Value>, overrides: &mut Map<String, Value>) {
    overrides.retain(|key, value| match (value, robot.get(key)) {
        (Value::Null, robot) => robot.is_some(),
        (Value::Object(child), robot) => {
            let empty = Map::new();
            let robot = robot.and_then(Value::as_object).unwrap_or(&empty);
            prune(robot, child);
            !child.is_empty()
        }
        (value, Some(robot)) => !same(value, robot),
        (_, None) => true,
    });
}

fn same(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(a), Value::Number(b)) => a.as_f64() == b.as_f64(),
        (Value::Array(a), Value::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b).all(|(a, b)| same(a, b))
        }
        (Value::Object(a), Value::Object(b)) => {
            a.len() == b.len() && a.iter().all(|(k, v)| b.get(k).is_some_and(|w| same(v, w)))
        }
        (a, b) => a == b,
    }
}

/// Converts TOML to the JSON shape used for override comparisons.
pub fn toml_to_json(toml: &str) -> Result<Map<String, Value>, String> {
    let table: toml::Table = toml::from_str(toml).map_err(|e| format!("robot config: {e}"))?;
    match serde_json::to_value(table).map_err(|e| e.to_string())? {
        Value::Object(map) => Ok(map),
        _ => unreachable!(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn object(value: Value) -> Map<String, Value> {
        value.as_object().unwrap().clone()
    }

    #[test]
    fn merge_keeps_comments_and_edits_nested_tables() {
        let robot = "# Spot\ntag_size = 0.1651\n\n[cameras.front]\nserial = \"A\" # left\nmount = { x = 0.2, pitch = 10 }\n";
        let merged = merge(
            robot,
            &object(json!({
                "cameras": {
                    "front": { "serial": null, "port": "usb1", "mount": { "pitch": 12.5 } },
                    "back": { "serial": "B" },
                },
            })),
        )
        .unwrap();
        assert!(merged.starts_with("# Spot\n"), "{merged}");
        let config: toml::Table = toml::from_str(&merged).unwrap();
        let front = &config["cameras"]["front"];
        assert!(front.get("serial").is_none());
        assert_eq!(front["port"].as_str(), Some("usb1"));
        assert_eq!(front["mount"]["x"].as_float(), Some(0.2));
        assert_eq!(front["mount"]["pitch"].as_float(), Some(12.5));
        assert_eq!(config["cameras"]["back"]["serial"].as_str(), Some("B"));
    }

    #[test]
    fn prune_drops_matching_values_and_empty_tables() {
        let robot = toml_to_json(
            "ignored_tags = [1, 2]\n[cameras.front]\nserial = \"A\"\nmount = { x = 1 }\n",
        )
        .unwrap();
        let mut overrides = object(json!({
            "ignored_tags": [1, 2],
            "cameras": {
                "front": { "serial": "A", "port": null, "mount": { "x": 1.0, "y": 0.5 } },
                "back": { "port": null },
            },
        }));
        prune(&robot, &mut overrides);
        assert_eq!(
            Value::Object(overrides),
            json!({ "cameras": { "front": { "mount": { "y": 0.5 } } } })
        );
    }
}
