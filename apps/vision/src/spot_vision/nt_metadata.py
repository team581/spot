"""Slow-changing acknowledgement metadata uses ordinary typed NT topics."""

from dataclasses import asdict

from .protocol import content_hash


class AcknowledgementPublisher:
    def __init__(self, instance, root, options):
        self.instance, self.root, self.options = instance, root, options
        self.publishers = {}
        self.header = instance.getStringTopic(root + "/config/ack").publish(options)

    def _set(self, name, value):
        if name not in self.publishers:
            kind = (
                "Boolean"
                if isinstance(value, bool)
                else "Integer"
                if isinstance(value, int)
                else "StringArray"
                if isinstance(value, list)
                else "String"
            )
            self.publishers[name] = getattr(self.instance, "get" + kind + "Topic")(
                self.root + "/config/acknowledgement/" + name
            ).publish(self.options)
        self.publishers[name].set(value)

    def set(self, message):
        values = asdict(message)
        cameras = values.pop("cameras")
        for name, value in values.items():
            self._set(name, value)
        for camera in cameras:
            for name, value in camera.items():
                self._set("cameras/" + camera["camera_name"] + "/" + name, value)
        self._set("camera_names", [camera["camera_name"] for camera in cameras])
        # Receiver checks this digest against the complete metadata snapshot.
        self.header.set(content_hash(message))

    def close(self):
        self.header.close()
        for publisher in self.publishers.values():
            publisher.close()
