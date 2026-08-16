"use strict";

const devicesEl = document.getElementById("devices");
const statusEl = document.getElementById("status");
const logEl = document.getElementById("log");
const autoEl = document.getElementById("autorefresh");

// Re-rendering while somebody drags a slider would reset it, so pause briefly
// after every interaction.
let pausedUntil = 0;

function pause(ms) {
  pausedUntil = Date.now() + ms;
}

function log(message, isError) {
  const line = document.createElement("div");
  line.textContent = new Date().toLocaleTimeString() + " " + message;
  if (isError) {
    line.style.color = "red";
  }
  logEl.prepend(line);
  while (logEl.childElementCount > 8) {
    logEl.lastElementChild.remove();
  }
}

function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function button(label, onClick) {
  const node = el("button", label);
  node.onclick = () => {
    pause(1500);
    onClick();
  };
  return node;
}

function slider(value, min, max, onRelease) {
  const input = document.createElement("input");
  input.type = "range";
  input.min = String(min);
  input.max = String(max);
  input.value = String(value);
  input.onfocus = () => pause(30000);
  input.onchange = () => {
    pause(2000);
    onRelease(Number(input.value));
  };
  return input;
}

function numberInput(value, step) {
  const input = document.createElement("input");
  input.type = "number";
  input.step = String(step || 0.5);
  input.value = value === undefined || value === null ? "" : String(value);
  input.size = 6;
  input.onfocus = () => pause(30000);
  return input;
}

async function send(guid, number, command) {
  try {
    const response = await fetch(
      `/api/devices/${guid}/channels/${number}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(command),
      }
    );
    const text = await response.text();
    if (!response.ok) {
      log(`channel ${number}: ${response.status} ${text}`, true);
      return;
    }
    log(`channel ${number}: ${JSON.stringify(command)} sent`);
    setTimeout(refresh, 400);
  } catch (error) {
    log(`channel ${number}: ${error}`, true);
  }
}

function describeValue(channel) {
  const value = channel.value || {};
  const parts = [];
  for (const [key, entry] of Object.entries(value)) {
    if (key === "raw" || entry === null || entry === undefined) {
      continue;
    }
    parts.push(`${key}=${entry}`);
  }
  if (parts.length === 0) {
    parts.push(`raw=${value.raw}`);
  }
  return parts.join(" ");
}

function renderControls(guid, channel) {
  const box = el("span");
  const kind = channel.kind;
  const value = channel.value || {};
  const push = (command) => send(guid, channel.number, command);

  const addOnOff = () => {
    box.append(
      button("On", () => push({ action: "on" })),
      button("Off", () => push({ action: "off" })),
      button("Toggle", () => push({ action: "toggle" }))
    );
  };

  const addShutterButtons = () => {
    box.append(
      button("Open", () => push({ action: "open" })),
      button("Close", () => push({ action: "close" })),
      button("Stop", () => push({ action: "stop" })),
      button("Step", () => push({ action: "step" }))
    );
  };

  if (kind === "relay") {
    addOnOff();
  } else if (kind === "roller_shutter" || kind === "facade_blind") {
    addShutterButtons();
    const position = Math.max(0, Number(value.position) || 0);
    box.append(
      " closed% ",
      slider(position, 0, 100, (v) => push({ action: "position", position: v }))
    );
    if (kind === "facade_blind") {
      const tilt = Math.max(0, Number(value.tilt) || 0);
      box.append(
        " tilt% ",
        slider(tilt, 0, 100, (v) => push({ action: "tilt", tilt: v }))
      );
    }
  } else if (kind === "dimmer" || kind === "rgb" || kind === "dimmer_rgb") {
    box.append(
      button("On", () => push({ action: "on" })),
      button("Off", () => push({ action: "off" }))
    );
    if (kind !== "rgb") {
      box.append(
        " brightness ",
        slider(Number(value.brightness) || 0, 0, 100, (v) =>
          push({ action: "brightness", brightness: v })
        )
      );
    }
    if (kind !== "dimmer") {
      const color = document.createElement("input");
      color.type = "color";
      color.value = value.color || "#ffffff";
      color.onfocus = () => pause(30000);
      color.onchange = () => {
        pause(2000);
        push({ action: "color", color: color.value });
      };
      box.append(" color ", color);
      box.append(
        " color brightness ",
        slider(Number(value.color_brightness) || 0, 0, 100, (v) =>
          push({ action: "color_brightness", color_brightness: v })
        )
      );
    }
  } else if (kind === "valve_open_close") {
    box.append(
      button("Open", () => push({ action: "open" })),
      button("Close", () => push({ action: "close" }))
    );
  } else if (kind === "valve_percentage") {
    box.append(
      button("Open", () => push({ action: "open" })),
      button("Close", () => push({ action: "close" })),
      " closed% ",
      slider(Number(value.closed_percent) || 0, 0, 100, (v) =>
        push({ action: "position", position: v })
      )
    );
  } else if (kind === "hvac") {
    const heat = numberInput(value.setpoint_heat, 0.5);
    const cool = numberInput(value.setpoint_cool, 0.5);
    box.append(
      button("Off", () => push({ action: "off" })),
      button("Heat", () => push({ action: "heat" })),
      button("Cool", () => push({ action: "cool" })),
      button("Auto", () => push({ action: "auto" })),
      button("Weekly", () => push({ action: "weekly_schedule" })),
      " heat ",
      heat,
      " cool ",
      cool,
      button("Set", () => {
        const command = { action: "setpoint" };
        if (heat.value !== "") {
          command.setpoint_heat = Number(heat.value);
        }
        if (cool.value !== "") {
          command.setpoint_cool = Number(cool.value);
        }
        push(command);
      })
    );
  } else if (kind === "thermostat_heatpol") {
    const setpoint = numberInput(value.preset_temperature, 0.5);
    box.append(
      button("On", () => push({ action: "on" })),
      button("Off", () => push({ action: "off" })),
      " setpoint ",
      setpoint,
      button("Set", () => push({ action: "setpoint", setpoint: Number(setpoint.value) }))
    );
  } else if (kind === "digiglass") {
    const mask = numberInput(value.mask, 1);
    box.append(
      button("All transparent", () => push({ action: "on" })),
      button("All opaque", () => push({ action: "off" })),
      " mask ",
      mask,
      button("Set", () => push({ action: "mask", mask: Number(mask.value) }))
    );
  } else if (kind === "engine_speed") {
    box.append(
      " speed ",
      slider(Number(value.speed) || 0, 0, 100, (v) => push({ action: "speed", speed: v }))
    );
  } else {
    box.append(el("i", "read only"));
  }

  return box;
}

function renderChannel(guid, channel) {
  const row = el("li");
  const title = el(
    "b",
    `#${channel.number} ${channel.function_name} (${channel.type_name})`
  );
  row.append(title, " ", el("code", describeValue(channel)), document.createElement("br"));
  row.append(renderControls(guid, channel));
  if (channel.extended) {
    row.append(
      document.createElement("br"),
      el("small", "extended: " + JSON.stringify(channel.extended))
    );
  }
  return row;
}

function renderDevice(device) {
  const section = el("div");
  section.append(
    el("h2", `${device.name} ${device.online ? "[online]" : "[offline]"}`),
    el(
      "small",
      `${device.guid} | ${device.soft_ver} | proto ${device.proto_version}` +
        (device.email ? ` | ${device.email}` : "")
    )
  );
  const list = el("ul");
  for (const channel of device.channels) {
    list.append(renderChannel(device.guid, channel));
  }
  section.append(list);
  for (const sub of device.sub_devices || []) {
    section.append(el("small", `subdevice ${sub.sub_device_id}: ${sub.name}`));
  }
  section.append(document.createElement("hr"));
  return section;
}

async function refresh() {
  try {
    const response = await fetch("/api/devices");
    const data = await response.json();
    statusEl.textContent = ` ${data.devices.length} device(s), updated ${new Date().toLocaleTimeString()}`;
    devicesEl.replaceChildren();
    if (data.devices.length === 0) {
      devicesEl.append(el("p", "No devices connected yet."));
      return;
    }
    for (const device of data.devices) {
      devicesEl.append(renderDevice(device));
    }
  } catch (error) {
    statusEl.textContent = ` error: ${error}`;
  }
}

document.getElementById("refresh").onclick = () => {
  pausedUntil = 0;
  refresh();
};

setInterval(() => {
  if (autoEl.checked && Date.now() >= pausedUntil) {
    refresh();
  }
}, 2000);

refresh();
