package com.team581.spot;

/**
 * An estimate with its frame's capture time.
 *
 * @param timestampSeconds The frame's capture time, in FPGA seconds.
 */
public record TimestampedEstimate(double timestampSeconds, SpotEstimate estimate) {}
