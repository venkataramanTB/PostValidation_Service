/* eslint-disable unicode-bom */
import React, { useState, useRef, useEffect, useCallback } from "react";
import { gsap } from "gsap";
/* eslint-disable no-unused-vars */
import { Box, Card, Typography, Button, Grid, CircularProgress } from "@mui/material";
/* eslint-enable no-unused-vars */
import api from "../services/api";

/* ─────────────────────────────────────────
   GLOBAL STYLES (injected once)
───────────────────────────────────────── */
const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=Instrument+Sans:wght@400;600;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --cream:    #f0ebe0;
    --cream-dk: #e2dace;
    --warm-mid: #c8bfad;
    --warm-drk: #a09283;
    --leather:  #8b6f4e;
    --copper:   #b87333;
    --copper-lt:#d4935f;
    --steel:    #5a6475;
    --ink:      #2c2420;
    --ink-lt:   #5c4e44;
    --shadow-a: rgba(0,0,0,.45);
    --shadow-b: rgba(255,255,255,.85);
    --active:   #c0392b;
    --active-lt:#e74c3c;
    --green:    #27ae60;
  }

  body {
    font-family: 'Instrument Sans', sans-serif;
    background: var(--cream-dk);
    color: var(--ink);
    min-height: 100vh;
  }

  select {
    appearance: none;
    -webkit-appearance: none;
    -moz-appearance: none;
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    letter-spacing: .03em;
    background: linear-gradient(145deg, #ddd6c6, #c8bfad);
    color: var(--ink);
    border: 1px solid rgba(0,0,0,.08);
    outline: none;
    cursor: pointer;
    width: 100%;
    padding: 9px 32px 9px 12px;
    border-radius: 10px;
    box-shadow:
      inset 3px 3px 8px rgba(0,0,0,.22),
      inset -2px -2px 6px rgba(255,255,255,.6);
    transition: box-shadow .2s ease, border-color .2s ease;
  }
  select:focus {
    border-color: var(--copper);
    box-shadow:
      inset 3px 3px 8px rgba(0,0,0,.22),
      inset -2px -2px 6px rgba(255,255,255,.6),
      0 0 0 2px rgba(184,115,51,.18);
  }
  select:hover {
    border-color: rgba(0,0,0,.18);
  }
  select option {
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    background: #e8e2d4;
    color: var(--ink);
    padding: 6px 10px;
  }
  select option:checked {
    background: linear-gradient(135deg, #d4935f, #b87333);
    color: #faf4e8;
  }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; margin: 4px 0; }
  ::-webkit-scrollbar-thumb {
    background: var(--warm-drk);
    border-radius: 3px;
    box-shadow: inset 1px 1px 3px rgba(0,0,0,.3);
  }
  ::-webkit-scrollbar-thumb:hover {
    background: var(--leather);
  }
`;

if (!document.getElementById("pvs-css")) {
  const s = document.createElement("style");
  s.id = "pvs-css";
  s.textContent = GLOBAL_CSS;
  document.head.appendChild(s);
}

/* ─────────────────────────────────────────
   UNIFIED INSTRUMENT PANEL LOADER
   Replaces ValidationLoader + GeminiLoader
───────────────────────────────────────── */
const InstrumentPanelLoader = ({
  title         = "INSTRUMENT ENGINE",
  statusLabel   = "SYS:ACTIVE",
  statusRunning = "RUNNING",
  stageDefault  = "Initializing...",
  dotLabels     = ["Step 1", "Step 2", "Step 3", "Done"],
  dotPadding    = "0 8px",
  progress      = 0,
  show          = false,
  stage         = "",
  eta           = null,
}) => {
  const overlayRef = useRef(null);
  const numRef     = useRef(null);
  const barFillRef = useRef(null);
  const segRefs    = useRef([]);
  const dotRefs    = useRef([]);
  const scanRef    = useRef(null);
  const glowRef    = useRef(null);

  /* Reset dot refs array length when dotLabels change */
  dotRefs.current = dotRefs.current.slice(0, dotLabels.length);

  useEffect(() => {
    if (!overlayRef.current) return;
    if (show) {
      gsap.fromTo(overlayRef.current,
        { opacity: 0 },
        { opacity: 1, duration: .4, ease: "power2.out" }
      );
      if (scanRef.current) {
        gsap.fromTo(scanRef.current,
          { top: "-2%" },
          { top: "100%", duration: 3, repeat: -1, ease: "none" }
        );
      }
    } else {
      gsap.to(overlayRef.current, { opacity: 0, duration: .35, ease: "power2.in" });
      if (scanRef.current) gsap.killTweensOf(scanRef.current);
    }
  }, [show]);

  useEffect(() => {
    if (!show) return;

    if (numRef.current) {
      gsap.to(numRef.current, {
        innerText: progress,
        duration: .5, snap: { innerText: 1 }, ease: "none",
      });
    }
    if (barFillRef.current) {
      gsap.to(barFillRef.current, {
        width: `${progress}%`,
        duration: .55, ease: "power2.out",
      });
    }
    if (glowRef.current) {
      gsap.to(glowRef.current, {
        opacity: .15 + (progress / 100) * .45,
        duration: .6, ease: "power2.out",
      });
    }

    const SEG_COUNT = 20;
    segRefs.current.forEach((seg, i) => {
      if (!seg) return;
      const threshold = ((i + 1) / SEG_COUNT) * 100;
      const active    = progress >= threshold;
      const color     = i < 14 ? "#b87333" : i < 17 ? "#d4935f" : "#c0392b";
      gsap.to(seg, {
        background: active ? color : "rgba(44,36,32,.08)",
        boxShadow:  active ? `0 0 6px ${color}80` : "none",
        opacity:    active ? 1 : .35,
        duration: .2, ease: "power1.out", delay: i * .015,
      });
    });

    /* Evenly distribute dot thresholds across 0–100 */
    const n = dotLabels.length;
    const thresholds = dotLabels.map((_, i) =>
      n === 1 ? 100 : Math.round((i / (n - 1)) * 100)
    );
    dotRefs.current.forEach((dot, i) => {
      if (!dot) return;
      const active = progress >= thresholds[i];
      gsap.to(dot, {
        background: active
          ? "linear-gradient(135deg, #c8843a, #7a4e28)"
          : "linear-gradient(145deg, #d0c8b8, #bfb7a7)",
        boxShadow: active
          ? "0 0 10px rgba(184,115,51,.6), 3px 3px 8px rgba(0,0,0,.4)"
          : "inset 2px 2px 5px rgba(0,0,0,.25), inset -1px -1px 3px rgba(255,255,255,.6)",
        scale: active ? 1.15 : 1,
        duration: .3, ease: "back.out(2)", delay: i * .04,
      });
    });
  }, [progress, show, dotLabels]);

  const SEG_COUNT = 20;

  return (
    <div ref={overlayRef} style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(44,36,32,.55)",
      backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      pointerEvents: show ? "all" : "none",
      opacity: 0,
    }}>
      {/* Instrument-panel card */}
      <div style={{
        width: 400, padding: "48px 40px 40px",
        borderRadius: 30,
        background: "linear-gradient(160deg, #e8e2d4 0%, #cec6b4 50%, #c4bba8 100%)",
        boxShadow:
          "30px 30px 80px rgba(0,0,0,.55), " +
          "-16px -16px 45px rgba(255,255,255,.85), " +
          "inset 0 2px 0 rgba(255,255,255,.5), " +
          "inset 0 -1px 0 rgba(0,0,0,.12)",
        border: "1px solid rgba(255,255,255,.3)",
        display: "flex", flexDirection: "column", alignItems: "center",
        position: "relative",
      }}>
        {/* Brass corner rivets */}
        {[{top:16,left:16},{top:16,right:16},{bottom:16,left:16},{bottom:16,right:16}].map((pos,i) => (
          <div key={i} style={{
            position: "absolute", ...pos,
            width: 13, height: 13, borderRadius: "50%",
            background: "linear-gradient(135deg, #d4a95f, #8b6f4e, #c89b50)",
            boxShadow: "2px 2px 5px rgba(0,0,0,.45), -1px -1px 3px rgba(255,255,255,.4), inset 0 1px 1px rgba(255,255,255,.3)",
          }}>
            <div style={{ position: "absolute", top: "50%", left: "50%", width: "65%", height: 1.5,
              background: "rgba(0,0,0,.35)", transform: "translate(-50%,-50%)" }} />
            <div style={{ position: "absolute", top: "50%", left: "50%", width: "65%", height: 1.5,
              background: "rgba(0,0,0,.35)", transform: "translate(-50%,-50%) rotate(90deg)" }} />
          </div>
        ))}

        {/* Etched label plate */}
        <div style={{
          fontFamily: "'DM Mono', monospace",
          fontSize: 8, fontWeight: 500, letterSpacing: ".25em", textTransform: "uppercase",
          color: "var(--ink-lt)",
          padding: "4px 14px", borderRadius: 4, marginBottom: 18,
          background: "linear-gradient(145deg, #d8d0c0, #e0d8c8)",
          boxShadow: "inset 1px 1px 3px rgba(0,0,0,.2), inset -1px -1px 2px rgba(255,255,255,.5)",
          border: "1px solid rgba(0,0,0,.06)",
        }}>{title}</div>

        {/* LCD Screen */}
        <div style={{
          position: "relative", width: "100%",
          borderRadius: 14,
          background: "linear-gradient(165deg, #1a1812 0%, #252018 50%, #1e1a14 100%)",
          boxShadow:
            "inset 5px 5px 18px rgba(0,0,0,.7), " +
            "inset -3px -3px 10px rgba(255,255,255,.04), " +
            "3px 3px 10px rgba(0,0,0,.3), " +
            "-2px -2px 6px rgba(255,255,255,.15)",
          border: "2px solid rgba(0,0,0,.25)",
          padding: "28px 24px 22px",
          marginBottom: 20,
          overflow: "hidden",
        }}>
          <div ref={glowRef} style={{
            position: "absolute", inset: 0, borderRadius: 12,
            background: "radial-gradient(ellipse at 50% 40%, rgba(184,115,51,.15) 0%, transparent 70%)",
            opacity: .15, pointerEvents: "none",
          }} />
          <div ref={scanRef} style={{
            position: "absolute", left: 0, right: 0,
            height: "8%", top: "-2%",
            background: "linear-gradient(180deg, transparent, rgba(184,115,51,.06), transparent)",
            pointerEvents: "none",
          }} />
          <div style={{
            position: "absolute", inset: 0, borderRadius: 12,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.015) 1px, transparent 1px), " +
              "linear-gradient(90deg, rgba(255,255,255,.015) 1px, transparent 1px)",
            backgroundSize: "8px 8px",
            pointerEvents: "none",
          }} />

          {/* Top bar */}
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            marginBottom: 16, position: "relative",
          }}>
            <div style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 7, letterSpacing: ".3em", textTransform: "uppercase",
              color: "rgba(184,115,51,.4)",
            }}>{statusLabel}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{
                width: 5, height: 5, borderRadius: "50%",
                background: progress > 0 ? "#27ae60" : "#b87333",
                boxShadow: progress > 0
                  ? "0 0 8px rgba(39,174,96,.7)"
                  : "0 0 6px rgba(184,115,51,.5)",
              }} />
              <div style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 7, letterSpacing: ".2em", textTransform: "uppercase",
                color: progress > 0 ? "rgba(39,174,96,.6)" : "rgba(184,115,51,.4)",
              }}>{progress >= 100 ? "DONE" : progress > 0 ? statusRunning : "IDLE"}</div>
            </div>
          </div>

          {/* Big percentage */}
          <div style={{
            display: "flex", alignItems: "baseline", justifyContent: "center",
            gap: 4, marginBottom: 14, position: "relative",
          }}>
            <div ref={numRef} style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 56, fontWeight: 500, color: "#d4935f",
              lineHeight: 1,
              textShadow: "0 0 20px rgba(184,115,51,.5), 0 0 40px rgba(184,115,51,.2)",
              letterSpacing: ".06em",
            }}>0</div>
            <span style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 18, color: "rgba(184,115,51,.5)", fontWeight: 400,
            }}>%</span>
          </div>

          {/* Stage readout */}
          <div style={{
            fontFamily: "'DM Mono', monospace",
            fontSize: 10, letterSpacing: ".18em", textTransform: "uppercase",
            color: "rgba(212,147,95,.55)",
            textAlign: "center", marginBottom: 16,
            textShadow: "0 0 8px rgba(184,115,51,.3)",
          }}>
            {">"} {stage || stageDefault}
          </div>

          {/* LED segment bar */}
          <div style={{
            display: "flex", gap: 3, width: "100%", height: 14,
            padding: "3px 4px", borderRadius: 5,
            background: "rgba(0,0,0,.3)",
            boxShadow: "inset 2px 2px 6px rgba(0,0,0,.5), inset -1px -1px 3px rgba(255,255,255,.02)",
          }}>
            {Array.from({ length: SEG_COUNT }).map((_, i) => (
              <div key={i} ref={el => segRefs.current[i] = el} style={{
                flex: 1, borderRadius: 2,
                background: "rgba(44,36,32,.08)",
                opacity: .35, transition: "none",
              }} />
            ))}
          </div>

          {/* Bottom stats row */}
          <div style={{
            display: "flex", justifyContent: "space-between", marginTop: 14,
            position: "relative",
          }}>
            {[
              { label: "ETA", value: progress >= 100 ? "00:00" : (eta != null && eta > 0) ? `${Math.floor(eta / 60)}:${String(Math.floor(eta % 60)).padStart(2, '0')}` : progress > 0 ? "calc..." : "--:--" },
              { label: "PROC", value: `${Math.min(progress, 100)}%` },
              { label: "MEM",  value: "OK" },
            ].map((stat) => (
              <div key={stat.label} style={{ textAlign: "center" }}>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 7, letterSpacing: ".2em",
                  color: "rgba(184,115,51,.35)",
                }}>{stat.label}</div>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 10, letterSpacing: ".08em",
                  color: "rgba(212,147,95,.6)",
                  textShadow: "0 0 6px rgba(184,115,51,.25)",
                  marginTop: 2,
                }}>{stat.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Brass progress bar */}
        <div style={{
          width: "100%", height: 8, borderRadius: 4,
          background: "linear-gradient(145deg, #c0b8a6, #d0c8b8)",
          boxShadow: "inset 3px 3px 8px rgba(0,0,0,.35), inset -2px -2px 5px rgba(255,255,255,.55)",
          overflow: "hidden", marginBottom: 24, position: "relative",
        }}>
          <div ref={barFillRef} style={{
            height: "100%", width: "0%", borderRadius: 4,
            background: "linear-gradient(90deg, #d4a95f, #b87333, #8b6f4e)",
            boxShadow: "0 0 10px rgba(184,115,51,.5), inset 0 1px 1px rgba(255,255,255,.3)",
            transition: "none",
          }} />
        </div>

        {/* Step dots */}
        <div style={{
          display: "flex", justifyContent: "space-between",
          width: "100%", padding: dotPadding,
        }}>
          {dotLabels.map((label, i) => (
            <div key={`${label}-${i}`} style={{
              display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
            }}>
              <div ref={el => dotRefs.current[i] = el} style={{
                width: 14, height: 14, borderRadius: "50%",
                background: "linear-gradient(145deg, #d0c8b8, #bfb7a7)",
                boxShadow: "inset 2px 2px 5px rgba(0,0,0,.25), inset -1px -1px 3px rgba(255,255,255,.6)",
              }} />
              <span style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 7, letterSpacing: ".1em", textTransform: "uppercase",
                color: "var(--ink-lt)",
              }}>{label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

/* ─────────────────────────────────────────
   TOGGLE SWITCH
───────────────────────────────────────── */
const Toggle = ({ active, onClick, color = "var(--copper)" }) => {
  const knobRef  = useRef(null);

  useEffect(() => {
    if (!knobRef.current) return;
    gsap.to(knobRef.current, { x: active ? 20 : 0, duration: .25, ease: "back.out(2)" });
  }, [active]);

  return (
    <div
      onClick={onClick}
      style={{
        width: 44, height: 24, borderRadius: 12,
        background: active
          ? `linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 60%, black))`
          : "linear-gradient(145deg, #c8bfad, #d8d0c0)",
        boxShadow: active
          ? `inset 2px 2px 6px rgba(0,0,0,.4), 0 0 12px ${color}55`
          : "inset 3px 3px 8px rgba(0,0,0,.35), inset -2px -2px 6px rgba(255,255,255,.7)",
        cursor: "pointer",
        position: "relative",
        flexShrink: 0,
        transition: "background .25s, box-shadow .25s",
      }}
    >
      <div ref={knobRef} style={{
        position: "absolute", top: 3, left: 3,
        width: 18, height: 18, borderRadius: "50%",
        background: "linear-gradient(145deg, #f4ede0, #d8cfc0)",
        boxShadow: "3px 3px 8px rgba(0,0,0,.4), -1px -1px 4px rgba(255,255,255,.8)",
      }} />
    </div>
  );
};

/* ─────────────────────────────────────────
   NEUMORPHIC BUTTON
───────────────────────────────────────── */
const NeuBtn = ({ children, onClick, disabled, accent }) => {
  const ref = useRef(null);

  const down = () => gsap.to(ref.current, {
    boxShadow: "inset 4px 4px 14px rgba(0,0,0,.45), inset -3px -3px 10px rgba(255,255,255,.5)",
    scale: .97, duration: .1
  });
  const up = () => gsap.to(ref.current, {
    boxShadow: accent
      ? "10px 10px 28px rgba(0,0,0,.5), -4px -4px 16px rgba(255,255,255,.3)"
      : "10px 10px 28px rgba(0,0,0,.4), -6px -6px 20px rgba(255,255,255,.9)",
    scale: 1, duration: .2, ease: "back.out(2)"
  });

  return (
    <button
      ref={ref}
      onClick={disabled ? undefined : onClick}
      onMouseDown={down}
      onMouseUp={up}
      onMouseLeave={up}
      disabled={disabled}
      style={{
        fontFamily: "'Instrument Sans', sans-serif",
        fontWeight: 700,
        fontSize: 13,
        letterSpacing: ".08em",
        textTransform: "uppercase",
        padding: "14px 36px",
        borderRadius: 10,
        border: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        color: accent ? "#f8f0e0" : "var(--ink)",
        background: accent
          ? "linear-gradient(135deg, #c8843a, #7a4e28)"
          : "linear-gradient(145deg, #ede6d6, #cec5b5)",
        boxShadow: disabled
          ? "none"
          : accent
            ? "10px 10px 28px rgba(0,0,0,.5), -4px -4px 16px rgba(255,255,255,.3)"
            : "10px 10px 28px rgba(0,0,0,.4), -6px -6px 20px rgba(255,255,255,.9)",
        opacity: disabled ? .5 : 1,
        transition: "opacity .2s",
      }}
    >
      {children}
    </button>
  );
};

/* ─────────────────────────────────────────
   DROP ZONE
───────────────────────────────────────── */
const DropZone = ({ label, file, onFile, inputRef }) => {
  const ref = useRef(null);

  const enter = () => gsap.to(ref.current, {
    scale: 1.02,
    boxShadow: "inset 6px 6px 18px rgba(0,0,0,.35), inset -4px -4px 14px rgba(255,255,255,.7), 0 0 30px rgba(184,115,51,.2)",
    duration: .2
  });
  const leave = () => gsap.to(ref.current, {
    scale: 1,
    boxShadow: "10px 10px 30px rgba(0,0,0,.4), -8px -8px 22px rgba(255,255,255,.9)",
    duration: .2
  });

  return (
    <div
      ref={ref}
      onClick={() => inputRef.current.click()}
      onDragEnter={enter}
      onDragOver={e => e.preventDefault()}
      onDragLeave={leave}
      onDrop={e => { e.preventDefault(); leave(); const f = e.dataTransfer.files[0]; if (f && (f.name.endsWith(".xlsx") || f.name.endsWith(".csv"))) onFile(f); }}
      style={{
        flex: 1, padding: "40px 24px", textAlign: "center",
        borderRadius: 16, cursor: "pointer",
        background: "linear-gradient(145deg, #ede6d6, #d8cfc0)",
        boxShadow: "10px 10px 30px rgba(0,0,0,.4), -8px -8px 22px rgba(255,255,255,.9)",
        border: "1px solid rgba(255,255,255,.5)",
        userSelect: "none",
      }}
    >
      <div style={{ marginBottom: 18 }}>
        <svg width="52" height="60" viewBox="0 0 52 60" fill="none">
          <rect x="10" y="9" width="36" height="45" rx="3" fill="rgba(0,0,0,.08)" />
          <rect x="8" y="7" width="36" height="45" rx="3" fill="rgba(0,0,0,.12)" />
          <rect x="6" y="5" width="36" height="45" rx="3"
            fill={file ? "#e8d4b8" : "var(--cream)"}
            stroke="rgba(0,0,0,.18)" strokeWidth="1"
          />
          <line x1="13" y1="17" x2="35" y2="17" stroke="rgba(0,0,0,.15)" strokeWidth="1.5" strokeLinecap="round"/>
          <line x1="13" y1="24" x2="35" y2="24" stroke="rgba(0,0,0,.15)" strokeWidth="1.5" strokeLinecap="round"/>
          <line x1="13" y1="31" x2="27" y2="31" stroke="rgba(0,0,0,.15)" strokeWidth="1.5" strokeLinecap="round"/>
          {file ? (
            <path d="M15 42 L22 49 L38 33" stroke="#27ae60" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
          ) : (
            <>
              <path d="M24 42 L24 36 M24 36 L21 39 M24 36 L27 39" stroke="var(--copper)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              <line x1="19" y1="46" x2="29" y2="46" stroke="var(--copper)" strokeWidth="1.8" strokeLinecap="round"/>
            </>
          )}
        </svg>
      </div>

      <div style={{
        fontFamily: "'DM Serif Display', serif",
        fontSize: 17, color: "var(--ink)", marginBottom: 8,
      }}>{label}</div>

      {file ? (
        <div style={{
          fontFamily: "'DM Mono', monospace",
          fontSize: 11, color: "#27ae60",
          letterSpacing: ".05em",
          background: "rgba(39,174,96,.1)",
          padding: "5px 12px", borderRadius: 6,
          display: "inline-block",
          border: "1px solid rgba(39,174,96,.25)",
        }}>{file.name}</div>
      ) : (
        <div style={{
          fontFamily: "'DM Mono', monospace",
          fontSize: 11, color: "var(--ink-lt)", letterSpacing: ".05em",
        }}>drop .xlsx · click to browse</div>
      )}

      <input ref={inputRef} type="file" accept=".xlsx,.csv" hidden
        onChange={e => { const f = e.target.files[0]; if (f) onFile(f); }} />
    </div>
  );
};

/* ─────────────────────────────────────────
   STEPPER HEADER — 3 steps
───────────────────────────────────────── */
const StepperHeader = ({ active }) => {
  const steps = ["Upload Files", "Transform", "Review Mapping"];
  return (
    <div style={{ display: "flex", alignItems: "center", marginBottom: 44 }}>
      {steps.map((s, i) => (
        <React.Fragment key={s}>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 40, height: 40, borderRadius: "50%",
              background: i <= active
                ? "linear-gradient(135deg, #c8843a, #7a4e28)"
                : "linear-gradient(145deg, #ddd6c6, #c0b8a8)",
              boxShadow: i <= active
                ? "5px 5px 14px rgba(0,0,0,.5), -2px -2px 8px rgba(255,255,255,.4), 0 0 18px rgba(184,115,51,.35)"
                : "5px 5px 14px rgba(0,0,0,.3), -3px -3px 10px rgba(255,255,255,.7)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontFamily: "'DM Serif Display', serif",
              color: i <= active ? "#f8f0e0" : "var(--warm-drk)",
              fontSize: 17,
              transition: "all .5s ease",
            }}>{i + 1}</div>
            <div style={{
              fontFamily: "'Instrument Sans', sans-serif",
              fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase",
              color: i <= active ? "var(--copper)" : "var(--warm-drk)",
              fontWeight: 700, transition: "color .4s",
            }}>{s}</div>
          </div>

          {i < steps.length - 1 && (
            <div style={{
              flex: 1, height: 2, margin: "0 18px", marginBottom: 20,
              background: active > i
                ? "linear-gradient(90deg, #c8843a, #d4935f)"
                : "var(--warm-mid)",
              boxShadow: active > i ? "0 0 8px rgba(184,115,51,.6)" : "none",
              borderRadius: 1,
              transition: "all .6s ease",
            }} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
};

/* ─────────────────────────────────────────
   MAIN COMPONENT
───────────────────────────────────────── */
export default function PostValidationStepper() {
  const [activeStep,          setActiveStep]          = useState(0);
  const [sourceFile,          setSourceFile]          = useState(null);
  const [targetFile,          setTargetFile]          = useState(null);
  const [configFile,          setConfigFile]          = useState(null);
  const [configData,          setConfigData]          = useState(null);
  const [mappingFile,         setMappingFile]         = useState(null);
  const [rows,                setRows]                = useState([]);
  const [targetOptions,       setTargetOptions]       = useState([]);
  const [loading,             setLoading]             = useState(false);
  const [loaderType,          setLoaderType]          = useState("validation"); // "validation" | "gemini" | "transform"
  const [progress,            setProgress]            = useState(0);
  const [stage,               setStage]               = useState("");
  const [eta,                 setEta]                 = useState(null);
  const [error,               setError]               = useState("");
  const [outputAsZip,         setOutputAsZip]         = useState(false);
  const [sourceLabel,         setSourceLabel]         = useState("");
  const [targetLabel,         setTargetLabel]         = useState("");
  const [caseSensitive,       setCaseSensitive]       = useState(true);

  /* Transform-step state */
  const [transformedFile,     setTransformedFile]     = useState(null);    // File object returned from /transform
  const [transformStats,      setTransformStats]      = useState(null);    // { rulesApplied, cellsChanged, columnsChanged, totalRules }
  const [transformedFileName, setTransformedFileName] = useState("");

  const cardRef        = useRef(null);
  const step1Ref       = useRef(null);   // Step 0: Upload Files
  const step2Ref       = useRef(null);   // Step 1: Transform (NEW)
  const step3Ref       = useRef(null);   // Step 2: Review Mapping
  const activeStepRef  = useRef(0);      // mirror of activeStep for stable closures
  const sourceInput    = useRef();
  const targetInput    = useRef();
  const configInput    = useRef();
  const mappingInput   = useRef();
  const rowRefs        = useRef([]);

  /* ── Config file handler ── */
  const handleConfigUpload = useCallback((file) => {
    if (!file) return;
    setConfigFile(file);
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const parsed = JSON.parse(e.target.result);
        setConfigData(parsed);
      } catch {
        setError("Invalid config file — must be valid JSON.");
        setConfigFile(null);
        setConfigData(null);
      }
    };
    reader.onerror = () => {
      setError("Failed to read config file.");
      setConfigFile(null);
    };
    reader.readAsText(file);
  }, []);

  /* ── Save current config ── */
  const handleSaveConfig = useCallback(() => {
    const keys         = rows.filter(r => r.isKey).map(r => r.source);
    const mappings     = {};
    rows.forEach(r => {
      if (r.target && r.target.trim() !== "") mappings[r.source] = r.target;
    });
    const dateColumns    = rows.filter(r => r.isDate).map(r => r.source);
    const validateCols   = rows.filter(r => r.validate).map(r => r.source);
    const includeCols    = rows.filter(r => r.include).map(r => r.source);

    const config = {
      customerName: configData?.customerName || "default",
      instanceName: configData?.instanceName || "default",
      mappings,
      keyColumns:      keys,
      dateColumns,
      validateColumns: validateCols,
      includeColumns:  includeCols,
      outputAsZip,
      ...(configData?.hireActions            && { hireActions:            configData.hireActions }),
      ...(configData?.rehireActions           && { rehireActions:          configData.rehireActions }),
      ...(configData?.termActions             && { termActions:            configData.termActions }),
      ...(configData?.globalTransferActions   && { globalTransferActions:  configData.globalTransferActions }),
      ...(configData?.statusTypes             && { statusTypes:            configData.statusTypes }),
      ...(configData?.assignmentStatusRules   && { assignmentStatusRules:  configData.assignmentStatusRules }),
    };

    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${config.customerName}_${config.instanceName}_config.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [rows, outputAsZip, configData]);

  /* Card entrance */
  useEffect(() => {
    gsap.fromTo(cardRef.current,
      { y: 80, opacity: 0, scale: .95 },
      { y: 0, opacity: 1, scale: 1, duration: 1.1, ease: "expo.out" }
    );
  }, []);

  /* Step transition — generalized for 3 steps.
     Uses activeStepRef (not activeStep state) so the function is stable
     across re-renders and never captures a stale step index in async callbacks. */
  const transitionToStep = useCallback((targetStep) => {
    const currentStep = activeStepRef.current;
    const refs        = [step1Ref, step2Ref, step3Ref];
    const outEl       = refs[currentStep]?.current;
    const inEl        = refs[targetStep]?.current;
    if (!outEl || !inEl) return;

    const goingForward = targetStep > currentStep;

    gsap.to(outEl, {
      x: goingForward ? -60 : 60,
      opacity: 0,
      duration: .35,
      ease: "power2.in",
      onComplete: () => {
        activeStepRef.current = targetStep;   // keep ref in sync first
        setActiveStep(targetStep);
        gsap.set(inEl,  { display: "block" });
        gsap.set(outEl, { display: "none" });
        gsap.fromTo(inEl,
          { x: goingForward ? 60 : -60, opacity: 0 },
          { x: 0, opacity: 1, duration: .5, ease: "expo.out" }
        );
      }
    });
  }, []);  // stable — reads live value via ref, no deps needed

  /* Row stagger (fires when entering step 2 — Review Mapping) */
  useEffect(() => {
    if (activeStep !== 2 || rowRefs.current.length === 0) return;
    const validRefs = rowRefs.current.filter(Boolean);
    gsap.fromTo(validRefs,
      { x: 30, opacity: 0 },
      { x: 0, opacity: 1, stagger: .035, duration: .4, ease: "power3.out", delay: .15 }
    );
  }, [activeStep, rows]);

  /* ── Run Transform — Step 0 → Step 1 ── */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const runTransform = useCallback(async () => {
    if (!sourceFile || !mappingFile) return;

    setError("");
    setLoaderType("transform");
    setLoading(true);
    setProgress(0);
    setStage("Uploading files");

    try {
      const form = new FormData();
      form.append("sourceFile",  sourceFile);
      form.append("mappingFile", mappingFile);

      const res = await api.post(
        "/excel/post_validation/transform",
        form,
        {
          responseType: "blob",
          timeout: 300_000,
          onUploadProgress: e => {
            if (!e.total) return;
            const pct = Math.round((e.loaded / e.total) * 40);
            setProgress(pct);
            setStage("Uploading files");
          },
        }
      );

      setProgress(80);
      setStage("Applying transformation rules");

      /* Parse stats from response headers (Axios lowercases header names) */
      const rulesApplied   = parseInt(res.headers["x-transform-rules-applied"]   ?? "0", 10);
      const cellsChanged   = parseInt(res.headers["x-transform-cells-changed"]   ?? "0", 10);
      const columnsChanged = parseInt(res.headers["x-transform-columns-changed"] ?? "0", 10);
      const totalRules     = parseInt(res.headers["x-transform-total-rules"]     ?? "0", 10);

      setTransformStats({ rulesApplied, cellsChanged, columnsChanged, totalRules });

      /* Derive filename */
      let fname = `${sourceFile.name.replace(/\.[^.]+$/, "")}_transformed.xlsx`;
      const disposition = res.headers["content-disposition"];
      if (disposition && disposition.includes("filename=")) {
        fname = disposition.split("filename=")[1].replace(/"/g, "").trim();
      }
      setTransformedFileName(fname);

      /* Store as File so FormData later sends the correct filename */
      const blob = new Blob([res.data], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const file = new File([blob], fname, { type: blob.type });
      setTransformedFile(file);

      setProgress(100);
      setStage("Done");

      setTimeout(() => {
        setLoading(false);
        transitionToStep(1);
        setProgress(0);
      }, 400);

    } catch (err) {
      console.error("Transform error:", err);
      if (err.response?.status === 400)      setError("Invalid file format or mapping structure");
      else if (err.response?.status === 500) setError("Server error during transformation");
      else if (err.message)                  setError(err.message);
      else                                   setError("Transformation request failed");
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceFile, mappingFile]);

  /* ── Run Mapping — Step 1 → Step 2 ── */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const runMapping = async () => {
    if (!sourceFile || !targetFile) {
      setError("Please upload both files.");
      return;
    }

    setError("");
    setLoaderType("gemini");
    setLoading(true);
    setProgress(0);
    setStage("Uploading files");

    /* Use the transformed file if one was produced, otherwise the original */
    const sourceForMapping = transformedFile || sourceFile;

    try {
      const form = new FormData();
      form.append("legacyFile",    sourceForMapping);
      form.append("oracleFile",    targetFile);
      form.append("legacySheet",   "");
      form.append("oracleSheet",   "");
      form.append("customerName",  configData?.customerName || "default");
      form.append("instanceName",  configData?.instanceName || "default");
      if (configFile)  form.append("configFile",  configFile);
      if (configData)  form.append("configData",  JSON.stringify(configData));
      // mappingFile is a value-transformation file, not a column mapping file — do not send here

      let lastUpdate = 0;

      const submitRes = await api.post(
        "/excel/post_validation/data_mapping",
        form,
        {
          onUploadProgress: e => {
            if (!e.total) return;
            const now = Date.now();
            if (now - lastUpdate < 100) return;
            lastUpdate = now;
            const pct       = Math.round((e.loaded * 100) / e.total);
            const mappedPct = Math.round(pct * 0.05);
            requestAnimationFrame(() => {
              setProgress(mappedPct);
              setStage("Uploading files");
            });
          }
        }
      );

      const result = submitRes.data;

      const sourceCols = Array.isArray(result?.legacy_columns)  ? result.legacy_columns  : [];
      const targetCols = Array.isArray(result?.oracle_columns)  ? result.oracle_columns  : [];
      const suggested  = result?.suggested_mapping || {};
      const dateCols   = result?.date_columns      || [];

      if (!sourceCols.length || !targetCols.length)
        throw new Error("Invalid API response");

      setTargetOptions(targetCols);

      const cfgMappings     = configData?.mappings         || {};
      const cfgKeys         = configData?.keyColumns        || [];
      const cfgDateCols     = configData?.dateColumns       || [];
      const cfgValidateCols = configData?.validateColumns   || [];
      const cfgIncludeCols  = configData?.includeColumns    || [];
      const hasConfigOverride = Object.keys(cfgMappings).length > 0;

      setRows(
        sourceCols.map((col, i) => {
          const mappedTarget = hasConfigOverride
            ? (cfgMappings[col] != null ? cfgMappings[col] : "")
            : (suggested[col]  != null ? suggested[col]  : "");
          const hasMapping = mappedTarget !== "";
          return {
            id:       i,
            source:   col,
            target:   mappedTarget,
            isKey:    cfgKeys.includes(col),
            isDate:   hasConfigOverride ? cfgDateCols.includes(col)     : dateCols.includes(col),
            validate: hasConfigOverride ? cfgValidateCols.includes(col) : hasMapping,
            include:  cfgIncludeCols.includes(col),
          };
        })
      );

      if (configData?.outputAsZip != null) setOutputAsZip(configData.outputAsZip);

      setProgress(100);
      setStage("Done");

      setTimeout(() => {
        setLoading(false);
        transitionToStep(2);   // → Step 2: Review Mapping
        setProgress(0);
      }, 400);

    } catch (err) {
      console.error("Mapping error:", err);
      if (err.response) {
        const code = err.response.status;
        if      (code === 400) setError("Invalid Excel format");
        else if (code === 422) setError("Missing required fields");
        else if (code === 500) setError("Server processing error");
        else                   setError("Unexpected server error");
      } else if (err.message) {
        setError(err.message);
      } else if (err.request) {
        setError("Server not reachable");
      } else {
        setError("Request failed");
      }
      setLoading(false);
    }
  };

  const updateRow = (id, field, val) => {
    setRows(r => r.map(x => x.id === id ? { ...x, [field]: val } : x));
    const el = rowRefs.current[id];
    if (el) {
      gsap.fromTo(el,
        { backgroundColor: "rgba(184,115,51,.13)" },
        { backgroundColor: "transparent", duration: .7, ease: "power2.out" }
      );
    }
  };

  /* ── Validate (Step 2 → download result) ── */
  const handleValidate = async () => {
    const keys = rows.filter(r => r.isKey).map(r => r.source);

    if (keys.length === 0) {
      setError("Select at least one Key column before validating.");
      return;
    }

    const keysWithoutMapping = rows.filter(r => r.isKey && (!r.target || r.target.trim() === ""));
    if (keysWithoutMapping.length > 0) {
      setError(`Key column(s) missing target mapping: ${keysWithoutMapping.map(r => r.source).join(", ")}`);
      return;
    }

    try {
      setLoaderType("validation");
      setLoading(true);
      setProgress(0);
      setStage("Uploading files");
      setError("");

      const activeRows = rows.filter(r => r.validate && r.target && r.target.trim() !== "");

      if (activeRows.length === 0) {
        setError("No columns to validate. Assign target mappings and enable Validate.");
        return;
      }

      const mappings        = {};
      activeRows.forEach(r => { mappings[r.source] = r.target; });
      const includedColumns = activeRows.filter(r => r.include).map(r => r.source);
      const dateColumns     = activeRows.filter(r => r.isDate).map(r => r.source);

      /* Use the transformed file if one was produced */
      const sourceForValidation = transformedFile || sourceFile;

      const form = new FormData();
      form.append("legacyFile",              sourceForValidation);
      form.append("oracleFile",              targetFile);
      form.append("customerName",            configData?.customerName || "default");
      form.append("instanceName",            configData?.instanceName || "default");
      if (configFile)  form.append("configFile",  configFile);
      if (configData)  form.append("configData",  JSON.stringify(configData));
      if (mappingFile) form.append("mappingFile", mappingFile);
      form.append("mappings",                JSON.stringify(mappings));
      form.append("keyColumns",              JSON.stringify(keys));
      form.append("includedColumns",         JSON.stringify(includedColumns));
      form.append("dateColumns",             JSON.stringify(dateColumns));
      form.append("timestampColumns",        JSON.stringify([]));
      form.append("dateColumnstarget",       JSON.stringify(dateColumns));
      form.append("timestampColumnstarget",  JSON.stringify([]));
      form.append("legacySheet",             "");
      form.append("oracleSheet",             "");
      form.append("includeSourceTargetFiles", !outputAsZip);
      form.append("outputAsZip",             outputAsZip);
      form.append("sourceLabel",             sourceLabel.trim() || "Source");
      form.append("targetLabel",             targetLabel.trim() || "Target");
      form.append("caseSensitive",           caseSensitive);

      const submitRes = await api.post(
        "/excel/post_validation/validate_large",
        form,
        {
          timeout: 300_000,
          onUploadProgress: e => {
            if (!e.total) return;
            const pct = Math.min(Math.round((e.loaded * 100) / e.total), 100);
            setProgress(Math.round(pct * 0.02));
            setStage("Uploading files");
          }
        }
      );

      const { job_id } = submitRes.data;
      if (!job_id) throw new Error("No job_id returned from server");

      setStage("Processing started");
      setProgress(2);

      const POLL_INTERVAL = 1500;
      const MAX_POLL_TIME = 30 * 60 * 1000;
      const pollStart     = Date.now();

      const pollStatus = () => new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
          try {
            if (Date.now() - pollStart > MAX_POLL_TIME) {
              clearInterval(interval);
              reject(new Error("Validation timed out after 30 minutes"));
              return;
            }

            const statusRes = await api.get(
              `/excel/post_validation/status/${job_id}`,
              { timeout: 10000 }
            );

            const { status, progress: jobProgress, stage: jobStage, error: jobError } = statusRes.data;

            setProgress(jobProgress || 0);
            setStage(jobStage || "");
            if (statusRes.data.eta_seconds != null) setEta(statusRes.data.eta_seconds);

            if (status === "complete") {
              clearInterval(interval);
              resolve();
            } else if (status === "failed") {
              clearInterval(interval);
              reject(new Error(jobError || "Validation failed on the server"));
            }
          } catch (pollErr) {
            console.warn("Poll error (will retry):", pollErr.message);
          }
        }, POLL_INTERVAL);
      });

      await pollStatus();

      setStage("Downloading results");

      const downloadRes = await api.get(
        `/excel/post_validation/download/${job_id}`,
        { responseType: "blob", timeout: 600_000 }
      );

      const contentType = downloadRes.headers["content-type"]
        || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
      const blob = new Blob([downloadRes.data], { type: contentType });

      let filename    = "MythicsValidationResults.xlsx";
      const disposition = downloadRes.headers["content-disposition"];
      if (disposition && disposition.includes("filename=")) {
        filename = disposition.split("filename=")[1].replace(/"/g, "").trim();
      }

      const url  = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href  = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

      setProgress(100);
      setStage("Complete");

    } catch (err) {
      console.error(err);
      setError(err.message || "Validation failed");
    } finally {
      setLoading(false);
      setTimeout(() => { setStage(""); }, 2000);
    }
  };

  /* ── Step 0 "Next" handler ── */
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const handleNext = useCallback(() => {
    setError("");
    if (mappingFile) {
      runTransform();   // internally calls transitionToStep(1) on success
    } else {
      /* No mapping file — skip transform, clear any stale transform state */
      setTransformedFile(null);
      setTransformStats(null);
      setTransformedFileName("");
      transitionToStep(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mappingFile, runTransform]);

  const grid = {
    display: "grid",
    gridTemplateColumns: "minmax(160px, 1.5fr) minmax(180px, 1.5fr) 56px 56px 56px 56px",
    alignItems: "center",
    gap: "0 12px",
  };

  /* ── Loader config by type ── */
  const loaderProps = {
    validation: {
      title:         "VALIDATION ENGINE",
      statusLabel:   "SYS:ACTIVE",
      statusRunning: "RUNNING",
      stageDefault:  "Initializing...",
      dotLabels:     ["Upload", "Parse", "Compare", "Analyze", "Report", "Done"],
      dotPadding:    "0 8px",
    },
    gemini: {
      title:         "\u2726 GEMINI AI MAPPING",
      statusLabel:   "AI:GEMINI",
      statusRunning: "MAPPING",
      stageDefault:  "Connecting to Gemini...",
      dotLabels:     ["Reading", "Parsing", "Mapping", "Done"],
      dotPadding:    "0 28px",
    },
    transform: {
      title:         "\u2726 TRANSFORM ENGINE",
      statusLabel:   "SYS:TRANSFORM",
      statusRunning: "APPLYING",
      stageDefault:  "Applying rules...",
      dotLabels:     ["Upload", "Parse", "Apply", "Done"],
      dotPadding:    "0 28px",
    },
  };
  const lp = loaderProps[loaderType] || loaderProps.validation;
  const srcLabel = sourceLabel.trim() || "Source";
  const tgtLabel = targetLabel.trim() || "Target";

  return (
    <>
      <InstrumentPanelLoader
        progress={progress}
        show={loading}
        stage={stage}
        eta={eta}
        {...lp}
      />

      <div style={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        padding: "48px 32px",
        background: `
          radial-gradient(ellipse at 20% 10%, rgba(184,115,51,.07) 0%, transparent 55%),
          radial-gradient(ellipse at 80% 90%, rgba(90,100,117,.07) 0%, transparent 55%),
          #dfd8cc
        `,
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
      }}>
        <div ref={cardRef} style={{
          width: "100%",
          maxWidth: 1080,
          padding: 52,
          borderRadius: 24,
          background: "linear-gradient(160deg, #ede8dc 0%, #d8d0c0 100%)",
          boxShadow: "28px 28px 70px rgba(0,0,0,.5), -16px -16px 50px rgba(255,255,255,.95), inset 0 1px 0 rgba(255,255,255,.6)",
          border: "1px solid rgba(255,255,255,.4)",
          position: "relative",
          overflow: "hidden",
        }}>

          {/* Corner screws */}
          {[{top:16,left:16},{top:16,right:16},{bottom:16,left:16},{bottom:16,right:16}].map((pos, i) => (
            <div key={i} style={{
              position: "absolute", ...pos,
              width: 15, height: 15, borderRadius: "50%",
              background: "linear-gradient(135deg, #c0b8a8, #a09080)",
              boxShadow: "2px 2px 5px rgba(0,0,0,.45), -1px -1px 3px rgba(255,255,255,.5)",
            }}>
              <div style={{
                position: "absolute", top: "50%", left: "50%",
                width: "60%", height: 2,
                background: "rgba(0,0,0,.45)",
                transform: `translate(-50%,-50%) rotate(${45 + i * 45}deg)`,
              }} />
            </div>
          ))}

          <StepperHeader active={activeStep} />

          {/* ═══════════════════════════════════════
              STEP 0 — Upload Files
          ═══════════════════════════════════════ */}
          <div ref={step1Ref}>
            <div style={{
              fontFamily: "'DM Serif Display', serif",
              fontSize: 30, marginBottom: 6, color: "var(--ink)",
            }}>Upload Validation Files</div>
            <div style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 12, color: "var(--ink-lt)", letterSpacing: ".05em", marginBottom: 38,
            }}>Provide source and target .xlsx or .csv files to begin</div>

            <div style={{ display: "flex", gap: 24, marginBottom: 28 }}>
              <DropZone label="Source File"  file={sourceFile}  onFile={setSourceFile}  inputRef={sourceInput} />
              <DropZone label="Target File"  file={targetFile}  onFile={setTargetFile}  inputRef={targetInput} />
              <DropZone label="Mapping File" file={mappingFile} onFile={setMappingFile} inputRef={mappingInput} />
            </div>

            {/* Source / Target Label Overrides */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
              {[
                { label: "Source Label", placeholder: "Source", value: sourceLabel, setter: setSourceLabel },
                { label: "Target Label", placeholder: "Target", value: targetLabel, setter: setTargetLabel },
              ].map(({ label, placeholder, value, setter }) => (
                <div key={label} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <label style={{
                    fontFamily: "'DM Mono', monospace", fontSize: 9, fontWeight: 600,
                    letterSpacing: ".14em", textTransform: "uppercase", color: "var(--ink-lt)", paddingLeft: 2,
                  }}>{label}</label>
                  <div style={{ position: "relative" }}>
                    <input
                      type="text"
                      value={value}
                      onChange={e => setter(e.target.value)}
                      placeholder={placeholder}
                      style={{
                        width: "100%", padding: "10px 14px",
                        borderRadius: 10, border: "1px solid rgba(0,0,0,.08)", outline: "none",
                        fontFamily: "'Instrument Sans', sans-serif", fontSize: 13,
                        color: "var(--ink)",
                        background: "linear-gradient(145deg, #ddd6c6, #c8bfad)",
                        boxShadow: "inset 3px 3px 8px rgba(0,0,0,.22), inset -2px -2px 6px rgba(255,255,255,.6)",
                        transition: "box-shadow .2s, border-color .2s",
                        boxSizing: "border-box",
                      }}
                      onFocus={e => { e.target.style.borderColor = "var(--copper)"; e.target.style.boxShadow = "inset 3px 3px 8px rgba(0,0,0,.22), inset -2px -2px 6px rgba(255,255,255,.6), 0 0 0 2px rgba(184,115,51,.18)"; }}
                      onBlur={e  => { e.target.style.borderColor = "rgba(0,0,0,.08)"; e.target.style.boxShadow = "inset 3px 3px 8px rgba(0,0,0,.22), inset -2px -2px 6px rgba(255,255,255,.6)"; }}
                    />
                    {value && (
                      <button
                        onClick={() => setter("")}
                        title="Reset to default"
                        style={{
                          position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                          background: "none", border: "none", cursor: "pointer",
                          color: "var(--warm-drk)", fontSize: 12, lineHeight: 1, padding: 2,
                        }}
                      >✕</button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Optional Config Upload */}
            <div
              onClick={() => configInput.current?.click()}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f && f.name.endsWith(".json")) handleConfigUpload(f); }}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 22px", borderRadius: 14, cursor: "pointer",
                background: "linear-gradient(145deg, #e2dace, #d4cbbe)",
                boxShadow: "inset 2px 2px 6px rgba(0,0,0,.12), inset -2px -2px 5px rgba(255,255,255,.55), 4px 4px 12px rgba(0,0,0,.15), -3px -3px 8px rgba(255,255,255,.6)",
                border: configFile
                  ? "1px solid rgba(39,174,96,.35)"
                  : "1px dashed rgba(0,0,0,.12)",
                marginBottom: 28,
                transition: "border-color .25s, box-shadow .25s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 10,
                  background: configFile
                    ? "linear-gradient(135deg, rgba(39,174,96,.15), rgba(39,174,96,.08))"
                    : "linear-gradient(145deg, #d0c8b8, #c4baa8)",
                  boxShadow: configFile
                    ? "inset 1px 1px 3px rgba(0,0,0,.1)"
                    : "inset 2px 2px 5px rgba(0,0,0,.2), inset -1px -1px 3px rgba(255,255,255,.45)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                }}>
                  <span style={{ fontSize: 16 }}>{configFile ? "✓" : "⚙"}</span>
                </div>
                <div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 10, fontWeight: 600, letterSpacing: ".1em", textTransform: "uppercase",
                    color: "var(--ink)", marginBottom: 2,
                  }}>Configuration File <span style={{ fontWeight: 400, color: "var(--warm-drk)" }}>(optional)</span></div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 9, color: configFile ? "#27ae60" : "var(--warm-drk)", letterSpacing: ".04em",
                  }}>{configFile ? configFile.name : "Upload a .json config to pre-fill mappings & settings"}</div>
                </div>
              </div>
              {configFile && (
                <div
                  onClick={(e) => { e.stopPropagation(); setConfigFile(null); setConfigData(null); }}
                  style={{
                    fontFamily: "'DM Mono', monospace", fontSize: 9,
                    color: "var(--active)", cursor: "pointer",
                    padding: "4px 10px", borderRadius: 6,
                    background: "rgba(192,57,43,.08)",
                    border: "1px solid rgba(192,57,43,.15)",
                    letterSpacing: ".06em", textTransform: "uppercase",
                  }}
                >Remove</div>
              )}
              <input ref={configInput} type="file" accept=".json" hidden
                onChange={e => { const f = e.target.files[0]; if (f) handleConfigUpload(f); e.target.value = ""; }} />
            </div>

            {/* Mapping file info banner */}
            {mappingFile && (
              <div style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 16px", borderRadius: 10, marginBottom: 20,
                background: "rgba(184,115,51,.08)",
                border: "1px solid rgba(184,115,51,.2)",
              }}>
                <span style={{ fontSize: 14 }}>⚡</span>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 9, color: "var(--ink-lt)", letterSpacing: ".06em",
                }}>
                  Mapping file detected — clicking <strong>Next</strong> will run value transformations before column mapping
                </div>
              </div>
            )}

            <div style={{
              height: 1,
              background: "linear-gradient(90deg, transparent, var(--warm-mid), transparent)",
              marginBottom: 30,
            }} />

            {error && (
              <div style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 12, color: "var(--active)", letterSpacing: ".04em",
                marginBottom: 20,
                padding: "12px 16px", borderRadius: 10,
                background: "rgba(192,57,43,.08)",
                border: "1px solid rgba(192,57,43,.2)",
              }}>{error}</div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <NeuBtn onClick={handleNext} disabled={!sourceFile || !targetFile} accent>
                Next →
              </NeuBtn>
            </div>
          </div>

          {/* ═══════════════════════════════════════
              STEP 1 — Transform Review (NEW)
          ═══════════════════════════════════════ */}
          <div ref={step2Ref} style={{ display: "none" }}>
            <div style={{
              fontFamily: "'DM Serif Display', serif",
              fontSize: 30, marginBottom: 6, color: "var(--ink)",
            }}>Transform Preview</div>
            <div style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 12, color: "var(--ink-lt)", letterSpacing: ".05em", marginBottom: 32,
            }}>
              {transformedFile
                ? "Value transformations applied — review results before column mapping"
                : "No mapping file was uploaded — transformation step skipped"}
            </div>

            {transformedFile ? (
              <>
                {/* Transformed file card */}
                <div style={{
                  padding: "18px 24px", borderRadius: 14, marginBottom: 24,
                  background: "linear-gradient(145deg, #e0d8c8, #d2cab8)",
                  boxShadow: "inset 2px 2px 6px rgba(0,0,0,.12), inset -2px -2px 5px rgba(255,255,255,.55), 4px 4px 12px rgba(0,0,0,.15), -3px -3px 8px rgba(255,255,255,.6)",
                  border: "1px solid rgba(39,174,96,.3)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                    <div>
                      <div style={{
                        fontFamily: "'DM Mono', monospace",
                        fontSize: 9, fontWeight: 600, letterSpacing: ".14em", textTransform: "uppercase",
                        color: "#27ae60", marginBottom: 5,
                      }}>✓ Transformed File Ready</div>
                      <div style={{
                        fontFamily: "'DM Mono', monospace",
                        fontSize: 11, color: "var(--ink)",
                      }}>{transformedFileName}</div>
                    </div>

                    {/* Download transformed file */}
                    <button
                      onClick={() => {
                        if (!transformedFile) return;
                        const url = URL.createObjectURL(transformedFile);
                        const a   = document.createElement("a");
                        a.href     = url;
                        a.download = transformedFileName;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        URL.revokeObjectURL(url);
                      }}
                      style={{
                        fontFamily: "'Instrument Sans', sans-serif",
                        fontWeight: 700, fontSize: 10, letterSpacing: ".08em", textTransform: "uppercase",
                        padding: "9px 20px", borderRadius: 9, border: "none", cursor: "pointer",
                        color: "#f8f0e0",
                        background: "linear-gradient(135deg, #5a6475, #3d4654)",
                        boxShadow: "5px 5px 14px rgba(0,0,0,.35), -2px -2px 8px rgba(255,255,255,.4)",
                        transition: "transform .15s",
                      }}
                      onMouseDown={e => { e.currentTarget.style.transform = "scale(0.96)"; }}
                      onMouseUp={e   => { e.currentTarget.style.transform = "scale(1)"; }}
                      onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; }}
                    >↓ Download Transformed File</button>
                  </div>
                </div>

                {/* Stats grid */}
                {transformStats && (
                  <div style={{
                    display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28,
                  }}>
                    {[
                      { label: "Rules Applied",   value: transformStats.rulesApplied,   sub: `of ${transformStats.totalRules}` },
                      { label: "Cells Changed",   value: transformStats.cellsChanged,   sub: null },
                      { label: "Columns Changed", value: transformStats.columnsChanged, sub: null },
                      { label: "Total Rules",     value: transformStats.totalRules,     sub: null },
                    ].map(({ label, value, sub }) => (
                      <div key={label} style={{
                        padding: "18px 20px", borderRadius: 14, textAlign: "center",
                        background: "linear-gradient(145deg, #ddd6c6, #cec5b5)",
                        boxShadow: "inset 3px 3px 8px rgba(0,0,0,.2), inset -2px -2px 6px rgba(255,255,255,.6)",
                      }}>
                        <div style={{
                          fontFamily: "'DM Mono', monospace",
                          fontSize: 28, fontWeight: 500, color: "var(--copper)",
                          textShadow: "0 0 12px rgba(184,115,51,.3)",
                          lineHeight: 1, marginBottom: 6,
                        }}>
                          {value}
                          {sub && <span style={{ fontSize: 13, color: "var(--warm-drk)", marginLeft: 3 }}>{sub}</span>}
                        </div>
                        <div style={{
                          fontFamily: "'DM Mono', monospace",
                          fontSize: 8, letterSpacing: ".14em", textTransform: "uppercase",
                          color: "var(--ink-lt)",
                        }}>{label}</div>
                      </div>
                    ))}
                  </div>
                )}

                {transformStats && transformStats.rulesApplied === 0 && (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 12,
                    padding: "12px 18px", borderRadius: 10, marginBottom: 24,
                    background: "rgba(184,115,51,.07)",
                    border: "1px solid rgba(184,115,51,.2)",
                  }}>
                    <span style={{ fontSize: 16 }}>⚠</span>
                    <div style={{
                      fontFamily: "'DM Mono', monospace",
                      fontSize: 10, color: "var(--ink-lt)", letterSpacing: ".04em",
                    }}>
                      No transformation rules matched any values in the source file.
                      The original source file will be used for validation.
                    </div>
                  </div>
                )}
              </>
            ) : (
              /* No-transform info panel */
              <div style={{
                padding: "22px 26px", borderRadius: 14, marginBottom: 28,
                background: "linear-gradient(145deg, #e0d8c8, #d2cab8)",
                boxShadow: "inset 2px 2px 6px rgba(0,0,0,.12), inset -2px -2px 5px rgba(255,255,255,.55)",
                border: "1px dashed rgba(0,0,0,.15)",
                display: "flex", alignItems: "flex-start", gap: 16,
              }}>
                <span style={{ fontSize: 22, flexShrink: 0, marginTop: 2 }}>ℹ</span>
                <div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 9, fontWeight: 600, letterSpacing: ".12em", textTransform: "uppercase",
                    color: "var(--ink)", marginBottom: 5,
                  }}>Transformation Skipped</div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 11, color: "var(--ink-lt)", lineHeight: 1.6,
                  }}>
                    No mapping file was uploaded. The original source file will be used for column mapping
                    and validation. To enable value transformations, go back and upload a mapping file (.xlsx or .csv)
                    with columns: <em>Column_Name</em>, <em>Old_Value</em>, <em>New_Value</em>.
                  </div>
                </div>
              </div>
            )}

            {error && (
              <div style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 12, color: "var(--active)", letterSpacing: ".04em",
                marginBottom: 20,
                padding: "12px 16px", borderRadius: 10,
                background: "rgba(192,57,43,.08)",
                border: "1px solid rgba(192,57,43,.2)",
              }}>{error}</div>
            )}

            <div style={{
              display: "flex", justifyContent: "space-between", marginTop: 8,
              alignItems: "center", flexWrap: "wrap", gap: 12,
            }}>
              <NeuBtn onClick={() => transitionToStep(0)}>← Back</NeuBtn>
              <NeuBtn onClick={runMapping} disabled={!sourceFile || !targetFile} accent>
                Run Mapping →
              </NeuBtn>
            </div>
          </div>

          {/* ═══════════════════════════════════════
              STEP 2 — Review Mapping (was Step 1)
          ═══════════════════════════════════════ */}
          <div ref={step3Ref} style={{ display: "none" }}>
            {/* Title row */}
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
              <div>
                <div style={{
                  fontFamily: "'DM Serif Display', serif",
                  fontSize: 28, marginBottom: 4, color: "var(--ink)",
                  lineHeight: 1.2,
                }}>Column Configuration</div>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 10, color: "var(--warm-drk)", letterSpacing: ".06em",
                }}>
                  {rows.length} columns · {rows.filter(r => r.isKey).length} key{rows.filter(r=>r.isKey).length !== 1 ? "s" : ""} selected
                  {configData && <span style={{ color: "#27ae60", marginLeft: 8 }}>· config loaded</span>}
                  {transformedFile && <span style={{ color: "var(--copper)", marginLeft: 8 }}>· using transformed source</span>}
                </div>
              </div>

              {/* Legend */}
              <div style={{
                display: "flex", gap: 14, alignItems: "center",
                padding: "6px 16px", borderRadius: 10,
                background: "linear-gradient(145deg, #ddd6c6, #cec5b5)",
                boxShadow: "inset 2px 2px 5px rgba(0,0,0,.15), inset -1px -1px 3px rgba(255,255,255,.5)",
              }}>
                {[["Key","#b87333"],["Date","#5a6475"],["Validate","#27ae60"],["Include","#c0392b"]].map(([l,c]) => (
                  <div key={l} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <div style={{
                      width: 6, height: 6, borderRadius: "50%", background: c,
                      boxShadow: `0 0 6px ${c}55`,
                    }} />
                    <span style={{
                      fontFamily: "'DM Mono', monospace", fontSize: 8,
                      color: "var(--ink-lt)", letterSpacing: ".1em", textTransform: "uppercase",
                      fontWeight: 500,
                    }}>{l}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Save Config bar */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              marginBottom: 16,
              padding: "10px 18px", borderRadius: 12,
              background: "linear-gradient(145deg, #e0d8c8, #d2cab8)",
              boxShadow: "4px 4px 12px rgba(0,0,0,.18), -3px -3px 8px rgba(255,255,255,.65)",
              border: "1px solid rgba(255,255,255,.25)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 14 }}>💾</span>
                <div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 9, fontWeight: 600, letterSpacing: ".1em", textTransform: "uppercase",
                    color: "var(--ink)",
                  }}>Save Configuration</div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 8, color: "var(--warm-drk)", letterSpacing: ".04em",
                  }}>Export current mappings & toggles as reusable JSON config</div>
                </div>
              </div>
              <button
                onClick={handleSaveConfig}
                disabled={rows.length === 0}
                style={{
                  fontFamily: "'Instrument Sans', sans-serif",
                  fontWeight: 700, fontSize: 10, letterSpacing: ".1em", textTransform: "uppercase",
                  padding: "8px 20px", borderRadius: 8, border: "none", cursor: rows.length === 0 ? "not-allowed" : "pointer",
                  color: "#f8f0e0",
                  background: "linear-gradient(135deg, #5a6475, #3d4654)",
                  boxShadow: rows.length === 0 ? "none" : "5px 5px 14px rgba(0,0,0,.35), -2px -2px 8px rgba(255,255,255,.4)",
                  opacity: rows.length === 0 ? .5 : 1,
                  transition: "opacity .2s, transform .15s",
                }}
                onMouseDown={e => { if (rows.length > 0) e.currentTarget.style.transform = "scale(0.96)"; }}
                onMouseUp={e => { e.currentTarget.style.transform = "scale(1)"; }}
                onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; }}
              >Save Config →</button>
            </div>

            {/* ── Source & Target Column Preview Panels ── */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
              {/* Source Columns Panel */}
              <div style={{
                borderRadius: 14,
                background: "linear-gradient(160deg, #d6cebb, #c5bcaa)",
                boxShadow: "inset 4px 4px 12px rgba(0,0,0,.28), inset -2px -2px 8px rgba(255,255,255,.45)",
                border: "1px solid rgba(255,255,255,.18)",
                overflow: "hidden",
              }}>
                <div style={{
                  padding: "10px 18px",
                  background: "linear-gradient(180deg, rgba(184,115,51,.18) 0%, rgba(184,115,51,.07) 100%)",
                  borderBottom: "1px solid rgba(0,0,0,.1)",
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--copper)", boxShadow: "0 0 6px rgba(184,115,51,.6)" }} />
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, fontWeight: 600, letterSpacing: ".16em", textTransform: "uppercase", color: "var(--copper)" }}>
                    {srcLabel} Columns
                  </span>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: "var(--warm-drk)", marginLeft: "auto" }}>
                    {rows.length} cols
                  </span>
                </div>
                <div style={{ maxHeight: 180, overflowY: "auto", padding: "8px 0" }}>
                  {rows.map((r, i) => (
                    <div key={r.id} style={{
                      padding: "5px 18px",
                      fontFamily: "'DM Mono', monospace",
                      fontSize: 10, color: "var(--ink)",
                      letterSpacing: ".02em",
                      borderBottom: i < rows.length - 1 ? "1px solid rgba(0,0,0,.04)" : "none",
                      display: "flex", alignItems: "center", gap: 7,
                    }}>
                      <div style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0, background: r.isKey ? "var(--copper)" : "rgba(0,0,0,.15)", boxShadow: r.isKey ? "0 0 5px var(--copper)" : "none" }} />
                      {r.source}
                    </div>
                  ))}
                </div>
              </div>

              {/* Target Columns Panel */}
              <div style={{
                borderRadius: 14,
                background: "linear-gradient(160deg, #d6cebb, #c5bcaa)",
                boxShadow: "inset 4px 4px 12px rgba(0,0,0,.28), inset -2px -2px 8px rgba(255,255,255,.45)",
                border: "1px solid rgba(255,255,255,.18)",
                overflow: "hidden",
              }}>
                <div style={{
                  padding: "10px 18px",
                  background: "linear-gradient(180deg, rgba(90,100,117,.18) 0%, rgba(90,100,117,.07) 100%)",
                  borderBottom: "1px solid rgba(0,0,0,.1)",
                  display: "flex", alignItems: "center", gap: 8,
                }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--steel)", boxShadow: "0 0 6px rgba(90,100,117,.6)" }} />
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 9, fontWeight: 600, letterSpacing: ".16em", textTransform: "uppercase", color: "var(--steel)" }}>
                    {tgtLabel} Columns
                  </span>
                  <span style={{ fontFamily: "'DM Mono', monospace", fontSize: 8, color: "var(--warm-drk)", marginLeft: "auto" }}>
                    {targetOptions.length} cols
                  </span>
                </div>
                <div style={{ maxHeight: 180, overflowY: "auto", padding: "8px 0" }}>
                  {targetOptions.map((col, i) => (
                    <div key={col} style={{
                      padding: "5px 18px",
                      fontFamily: "'DM Mono', monospace",
                      fontSize: 10, color: "var(--ink)",
                      letterSpacing: ".02em",
                      borderBottom: i < targetOptions.length - 1 ? "1px solid rgba(0,0,0,.04)" : "none",
                      display: "flex", alignItems: "center", gap: 7,
                    }}>
                      <div style={{ width: 5, height: 5, borderRadius: "50%", flexShrink: 0, background: "var(--steel)", opacity: .5 }} />
                      {col}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* ── Column Mapping Table ── */}
            <div style={{
              fontFamily: "'DM Mono', monospace",
              fontSize: 8, fontWeight: 600, letterSpacing: ".18em", textTransform: "uppercase",
              color: "var(--warm-drk)", marginBottom: 10, paddingLeft: 4,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#27ae60", boxShadow: "0 0 5px rgba(39,174,96,.5)" }} />
              Match Source → Target
            </div>

            {/* Table */}
            <div style={{
              borderRadius: 16,
              background: "linear-gradient(160deg, #d6cebb, #c5bcaa)",
              boxShadow: "inset 5px 5px 16px rgba(0,0,0,.32), inset -3px -3px 12px rgba(255,255,255,.5)",
              overflow: "hidden",
              border: "1px solid rgba(255,255,255,.18)",
            }}>
              {/* Header */}
              <div style={{
                ...grid,
                padding: "13px 24px",
                background: "linear-gradient(180deg, rgba(0,0,0,.1) 0%, rgba(0,0,0,.05) 100%)",
                borderBottom: "1px solid rgba(0,0,0,.1)",
              }}>
                {[`${srcLabel} Column`, `${tgtLabel} Column`, "Key","Date","Validate","Include"].map((h, hi) => (
                  <div key={h} style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 8, fontWeight: 600, letterSpacing: ".16em",
                    textTransform: "uppercase",
                    color: "var(--warm-drk)",
                    textAlign: hi < 2 ? "left" : "center",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: hi < 2 ? "flex-start" : "center",
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                    textOverflow: "ellipsis",
                    minWidth: 0,
                  }}>{h}</div>
                ))}
              </div>

              {/* Rows */}
              <div style={{ maxHeight: 420, overflowY: "auto" }}>
                {rows.map((r, idx) => (
                  <div
                    key={r.id}
                    ref={el => rowRefs.current[idx] = el}
                    className="pvs-row"
                    style={{
                      ...grid,
                      padding: "10px 24px",
                      borderBottom: "1px solid rgba(0,0,0,.045)",
                      background: idx % 2 === 0 ? "transparent" : "rgba(0,0,0,.022)",
                      transition: "background .15s ease",
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = "rgba(184,115,51,.055)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = idx % 2 === 0 ? "transparent" : "rgba(0,0,0,.022)"; }}
                  >
                    {/* Source column name */}
                    <div
                      title={r.source}
                      style={{
                        fontFamily: "'DM Mono', monospace",
                        fontSize: 11, color: "var(--ink)",
                        letterSpacing: ".03em",
                        display: "flex", alignItems: "center", gap: 8,
                        overflow: "hidden", whiteSpace: "nowrap",
                        minWidth: 0,
                      }}
                    >
                      <div style={{
                        width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                        background: r.isKey ? "var(--copper)" : "rgba(0,0,0,.12)",
                        boxShadow: r.isKey ? "0 0 8px var(--copper)" : "none",
                        transition: "all .25s",
                      }} />
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{r.source}</span>
                    </div>

                    {/* Target dropdown */}
                    <div style={{ position: "relative", minWidth: 0, overflow: "hidden" }}>
                      <select
                        value={r.target}
                        title={r.target || "(no mapping)"}
                        onChange={e => {
                          const val = e.target.value;
                          updateRow(r.id, "target", val);
                          if (val === "") updateRow(r.id, "validate", false);
                          else if (!r.validate) updateRow(r.id, "validate", true);
                        }}
                        style={{ textOverflow: "ellipsis" }}
                      >
                        <option value="">(ignore — no mapping)</option>
                        {targetOptions.map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                      <div style={{
                        position: "absolute", right: 12, top: "50%",
                        transform: "translateY(-50%)",
                        pointerEvents: "none", color: "var(--warm-drk)", fontSize: 9,
                        lineHeight: 1,
                      }}>▾</div>
                    </div>

                    {/* Toggle switches */}
                    {[["isKey","#b87333"],["isDate","#5a6475"],["validate","#27ae60"],["include","#c0392b"]].map(([field,color]) => (
                      <div key={field} style={{ display: "flex", justifyContent: "center", alignItems: "center" }}>
                        <Toggle active={r[field]} onClick={() => updateRow(r.id, field, !r[field])} color={color} />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>

            {error && (
              <div style={{
                fontFamily: "'DM Mono', monospace",
                fontSize: 12, color: "var(--active)", letterSpacing: ".04em",
                marginTop: 18,
                padding: "12px 16px", borderRadius: 10,
                background: "rgba(192,57,43,.08)",
                border: "1px solid rgba(192,57,43,.2)",
              }}>{error}</div>
            )}

            {/* Case Sensitivity + Output Format toggles */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 24 }}>

              {/* Case Sensitivity */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 20px", borderRadius: 12,
                background: "linear-gradient(145deg, #ddd6c6, #cec5b5)",
                boxShadow: "inset 2px 2px 6px rgba(0,0,0,.18), inset -2px -2px 5px rgba(255,255,255,.55)",
                border: "1px solid rgba(255,255,255,.2)",
              }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 10, fontWeight: 600, letterSpacing: ".12em",
                    textTransform: "uppercase", color: "var(--ink)",
                  }}>Case Sensitivity</div>
                  <div style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 9, color: "var(--warm-drk)", letterSpacing: ".04em",
                  }}>
                    {caseSensitive ? "ABC ≠ abc — exact case match" : "ABC = abc — case ignored"}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 9, letterSpacing: ".08em", textTransform: "uppercase",
                    color: !caseSensitive ? "var(--ink)" : "var(--warm-drk)",
                    fontWeight: !caseSensitive ? 600 : 400,
                    transition: "color .25s",
                  }}>Off</span>
                  <Toggle active={caseSensitive} onClick={() => setCaseSensitive(s => !s)} color="var(--copper)" />
                  <span style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: 9, letterSpacing: ".08em", textTransform: "uppercase",
                    color: caseSensitive ? "var(--ink)" : "var(--warm-drk)",
                    fontWeight: caseSensitive ? 600 : 400,
                    transition: "color .25s",
                  }}>On</span>
                </div>
              </div>

              {/* Output format toggle */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 20px", borderRadius: 12,
              background: "linear-gradient(145deg, #ddd6c6, #cec5b5)",
              boxShadow: "inset 2px 2px 6px rgba(0,0,0,.18), inset -2px -2px 5px rgba(255,255,255,.55)",
              border: "1px solid rgba(255,255,255,.2)",
            }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 10, fontWeight: 600, letterSpacing: ".12em",
                  textTransform: "uppercase", color: "var(--ink)",
                }}>Output Format</div>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 9, color: "var(--warm-drk)", letterSpacing: ".04em",
                }}>
                  {outputAsZip
                    ? "Separate files bundled as .zip"
                    : "All results in a single .xlsx file"}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 9, letterSpacing: ".08em", textTransform: "uppercase",
                  color: !outputAsZip ? "var(--ink)" : "var(--warm-drk)",
                  fontWeight: !outputAsZip ? 600 : 400,
                  transition: "color .25s, font-weight .25s",
                }}>Single File</span>
                <Toggle active={outputAsZip} onClick={() => setOutputAsZip(z => !z)} color="var(--steel)" />
                <span style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 9, letterSpacing: ".08em", textTransform: "uppercase",
                  color: outputAsZip ? "var(--ink)" : "var(--warm-drk)",
                  fontWeight: outputAsZip ? 600 : 400,
                  transition: "color .25s, font-weight .25s",
                }}>Zip Bundle</span>
              </div>
              </div>
            </div>{/* end settings grid */}

            <div style={{
              display: "flex", justifyContent: "space-between", marginTop: 20,
              alignItems: "center", flexWrap: "wrap", gap: 12,
            }}>
              <NeuBtn onClick={() => transitionToStep(1)}>← Back</NeuBtn>
              <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
                <div style={{
                  fontFamily: "'DM Mono', monospace",
                  fontSize: 10, color: "var(--warm-drk)", letterSpacing: ".06em",
                  padding: "5px 14px", borderRadius: 8,
                  background: "rgba(0,0,0,.04)",
                  border: "1px solid rgba(0,0,0,.06)",
                }}>
                  {rows.filter(r => r.validate && r.target && r.target.trim() !== "").length} of {rows.length} cols to validate · {rows.filter(r => !r.target || r.target.trim() === "").length} ignored
                </div>
                <NeuBtn onClick={handleValidate} accent>Validate Mapping →</NeuBtn>
              </div>
            </div>
          </div>

        </div>
      </div>
    </>
  );
}
