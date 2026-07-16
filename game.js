const MAX_MISTAKES = 3;
const PUZZLE_PATH = "puzzles/example.json"; // swap for date-based lookup later

// 3x3 slot layout, index -> compass position
// 0 NW  1 N  2 NE
// 3 W   4 C  5 E
// 6 SW  7 S  8 SE
const CENTER_SLOT = 4;
const SLOT_POS = [
  { left: "1%", top: "1%" },
  { left: "35%", top: "1%" },
  { left: "69%", top: "1%" },
  { left: "1%", top: "35%" },
  { left: "35%", top: "35%" },
  { left: "69%", top: "35%" },
  { left: "1%", top: "69%" },
  { left: "35%", top: "69%" },
  { left: "69%", top: "69%" },
];

// axis (pair of opposite slots) claimed by the 1st, 2nd, 3rd, 4th category
// solved, in that order -- not tied to the category's index in the puzzle
const AXES = [
  [3, 5], // horizontal, through center
  [0, 8], // diagonal NW-SE
  [1, 7], // vertical
  [2, 6], // diagonal NE-SW
];

const els = {
  grid: document.getElementById("grid"),
  controls: document.getElementById("controls"),
  shuffleBtn: document.getElementById("shuffleBtn"),
  deselectBtn: document.getElementById("deselectBtn"),
  submitBtn: document.getElementById("submitBtn"),
  resultsBtn: document.getElementById("resultsBtn"),
  backBtn: document.getElementById("backBtn"),
  mistakeDots: document.getElementById("mistakeDots"),
  legend: document.getElementById("legend"),
  legendList: document.getElementById("legendList"),
  status: document.getElementById("status"),
};

let state = null;

async function loadPuzzle() {
  try {
    const res = await fetch(PUZZLE_PATH);
    if (!res.ok) throw new Error(`Could not load puzzle (${res.status})`);
    const puzzle = await res.json();
    initGame(puzzle);
  } catch (err) {
    els.status.textContent = "Kunde inte ladda pusslet. " + err.message;
  }
}

function initGame(puzzle) {
  const pivot = puzzle.pivot;

  const tiles = [{ word: pivot, isPivot: true, catIndexes: puzzle.categories.map((_, i) => i) }];
  puzzle.categories.forEach((cat, catIndex) => {
    cat.words.forEach((w) => tiles.push({ word: w, isPivot: false, catIndexes: [catIndex] }));
  });

  const slots = shuffle([0, 1, 2, 3, 4, 5, 6, 7, 8]);
  tiles.forEach((t, i) => (t.slot = slots[i]));

  state = {
    puzzle,
    tiles,
    tileEls: [],
    selected: new Set(),
    solvedCats: new Set(),
    solveOrder: [], // category indexes, in the order they were solved
    categoryLayout: {}, // catIndex -> { word: slot } for that category's non-pivot words
    pivotSlot: undefined, // unset until the first category is solved
    mistakes: 0,
    over: false,
  };

  buildTileEls();
  renderMistakes();
  render();
  bindControls();
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// Tiles are created once and kept in the DOM so left/top changes animate
// via CSS transition, instead of re-rendering innerHTML on every update.
function buildTileEls() {
  els.grid.innerHTML = "";
  state.tileEls = state.tiles.map((tile, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tile";
    btn.textContent = tile.word;
    btn.addEventListener("click", () => toggleTile(idx));
    els.grid.appendChild(btn);
    return btn;
  });
}

function toggleTile(idx) {
  if (state.over) return;
  if (state.selected.has(idx)) {
    state.selected.delete(idx);
  } else {
    if (state.selected.size >= 3) return;
    state.selected.add(idx);
  }
  els.submitBtn.disabled = state.selected.size !== 3;
  render();
}

function bindControls() {
  els.shuffleBtn.onclick = () => {
    if (state.over) return;
    // only shuffle tiles that aren't locked into a solved axis yet
    const freeIdxs = state.tiles
      .map((t, i) => i)
      .filter((i) => !isFixed(state.tiles[i]));
    const freeSlots = shuffle(freeIdxs.map((i) => state.tiles[i].slot));
    freeIdxs.forEach((i, k) => (state.tiles[i].slot = freeSlots[k]));
    render();
  };

  els.deselectBtn.onclick = () => {
    state.selected.clear();
    els.submitBtn.disabled = true;
    render();
  };

  els.submitBtn.onclick = submitGuess;

  els.resultsBtn.onclick = () => {
    els.legend.classList.toggle("hidden");
  };

  els.backBtn.onclick = () => {
    els.legend.classList.add("hidden");
  };
}

function isFixed(tile) {
  if (tile.isPivot) return state.pivotSlot !== undefined;
  const catIndex = tile.catIndexes[0];
  return !!(state.categoryLayout[catIndex] && state.categoryLayout[catIndex][tile.word] !== undefined);
}

function submitGuess() {
  const idxs = [...state.selected];
  const words = idxs.map((i) => state.tiles[i].word);

  const matchCat = state.puzzle.categories.findIndex((cat, i) => {
    if (state.solvedCats.has(i)) return false;
    const catWords = new Set([state.puzzle.pivot, ...cat.words]);
    return words.length === 3 && words.every((w) => catWords.has(w));
  });

  if (matchCat !== -1) {
    lockCategory(matchCat);
    state.selected.clear();
    els.submitBtn.disabled = true;
    const cat = state.puzzle.categories[matchCat];
    const allWords = [state.puzzle.pivot, ...cat.words].map((w) => w.toUpperCase());
    els.status.textContent = `Rätt! ${cat.title} — ${allWords.join(" · ")}`;
    render();
    checkWin();
  } else {
    state.mistakes += 1;
    renderMistakes();
    shakeSelected();
    els.status.textContent = "Fel grupp — försök igen.";
    if (state.mistakes >= MAX_MISTAKES) {
      endGame(false);
    } else {
      setTimeout(() => {
        state.selected.clear();
        els.submitBtn.disabled = true;
        render();
      }, 500);
    }
  }
}

function lockCategory(catIndex) {
  state.solvedCats.add(catIndex);
  const orderIdx = state.solveOrder.length;
  state.solveOrder.push(catIndex);

  if (orderIdx === 0) {
    // first solve: don't reveal the pivot yet. Scatter the pivot and this
    // category's two words randomly across the three axis-1 slots
    // (both endpoints plus the center) so any of the three could be it.
    const axisFull = shuffle([...AXES[0], CENTER_SLOT]);
    const words = state.puzzle.categories[catIndex].words;
    const entries = shuffle([state.puzzle.pivot, ...words]);
    state.categoryLayout[catIndex] = {};
    entries.forEach((w, i) => {
      if (w === state.puzzle.pivot) {
        state.pivotSlot = axisFull[i];
      } else {
        state.categoryLayout[catIndex][w] = axisFull[i];
      }
    });
  } else if (orderIdx === 1) {
    // second solve: the pivot is confirmed now -- snap it to true center,
    // and settle the first category onto axis-1's two endpoints
    state.pivotSlot = CENTER_SLOT;
    const cat0 = state.solveOrder[0];
    const cat0Words = state.puzzle.categories[cat0].words;
    const axis0 = shuffle(AXES[0]);
    state.categoryLayout[cat0] = { [cat0Words[0]]: axis0[0], [cat0Words[1]]: axis0[1] };

    const words = state.puzzle.categories[catIndex].words;
    const axis1 = shuffle(AXES[1]);
    state.categoryLayout[catIndex] = { [words[0]]: axis1[0], [words[1]]: axis1[1] };
  } else {
    // third / fourth solve: pivot already fixed, just claim the next axis
    const axis = shuffle(AXES[orderIdx]);
    const words = state.puzzle.categories[catIndex].words;
    state.categoryLayout[catIndex] = { [words[0]]: axis[0], [words[1]]: axis[1] };
  }

  relayout();
}

// Recomputes every tile's slot: fixed tiles (pivot + solved-category words)
// go to their assigned compass position, everything else gets shuffled
// into whatever slots are left over.
function relayout() {
  const taken = new Set();
  const fixedSlot = {}; // tile index -> slot

  state.tiles.forEach((tile, i) => {
    if (tile.isPivot) {
      if (state.pivotSlot !== undefined) {
        fixedSlot[i] = state.pivotSlot;
        taken.add(state.pivotSlot);
      }
    } else {
      const catIndex = tile.catIndexes[0];
      const layout = state.categoryLayout[catIndex];
      if (layout && layout[tile.word] !== undefined) {
        fixedSlot[i] = layout[tile.word];
        taken.add(layout[tile.word]);
      }
    }
  });

  const freeSlots = shuffle([0, 1, 2, 3, 4, 5, 6, 7, 8].filter((s) => !taken.has(s)));
  let k = 0;
  state.tiles.forEach((tile, i) => {
    if (fixedSlot[i] !== undefined) {
      tile.slot = fixedSlot[i];
    } else {
      tile.slot = freeSlots[k++];
    }
  });
}

function render() {
  state.tiles.forEach((tile, idx) => {
    const btn = state.tileEls[idx];
    const pos = SLOT_POS[tile.slot];
    btn.style.left = pos.left;
    btn.style.top = pos.top;

    btn.className = "tile"; // reset, then reapply state classes
    btn.style.background = ""; // clear any inline pivot gradient from a prior render
    if (state.selected.has(idx)) btn.classList.add("selected");

    if (tile.isPivot) {
      if (state.solveOrder.length === 1) {
        // still hidden among its axis-mates: same flat color, no tell
        btn.classList.add("solved", "cat-1");
      } else if (state.solveOrder.length >= 2) {
        // confirmed: blend the colors of every category it's known to be in
        btn.classList.add("solved", "pivot-blend");
        btn.style.background = pivotGradient();
      }
    } else {
      const catIndex = tile.catIndexes[0];
      if (state.solvedCats.has(catIndex)) {
        btn.classList.add("solved", `cat-${state.solveOrder.indexOf(catIndex) + 1}`);
      }
    }
  });
}

function pivotGradient() {
  const n = state.solveOrder.length;
  const step = 100 / n;
  const stops = state.solveOrder
    .map((_, i) => `var(--cat-${i + 1}) ${(i * step).toFixed(2)}% ${((i + 1) * step).toFixed(2)}%`)
    .join(", ");
  return `conic-gradient(from 0deg, ${stops})`;
}

function shakeSelected() {
  [...state.selected].forEach((i) => {
    const el = state.tileEls[i];
    el.classList.add("shake");
    el.addEventListener("animationend", () => el.classList.remove("shake"), { once: true });
  });
}

function renderMistakes() {
  els.mistakeDots.innerHTML = "";
  for (let i = 0; i < MAX_MISTAKES; i++) {
    const dot = document.createElement("span");
    dot.className = "dot" + (i < state.mistakes ? " spent" : "");
    els.mistakeDots.appendChild(dot);
  }
}

function checkWin() {
  if (state.solvedCats.size === state.puzzle.categories.length) {
    endGame(true);
  }
}

function endGame(won) {
  state.over = true;
  els.controls.querySelectorAll(".btn-outline, #submitBtn").forEach((b) => b.classList.add("hidden"));
  els.resultsBtn.classList.remove("hidden");
  els.status.textContent = won ? "Klart! Alla fyra kategorier lösta." : "Slut på försök — här är svaren.";
  render();
  buildLegend();
  els.legend.classList.remove("hidden");
}

function buildLegend() {
  els.legendList.innerHTML = "";
  // list in solve order; any never-guessed categories (loss case) appended after
  const order = [...state.solveOrder, ...state.puzzle.categories.map((_, i) => i).filter((i) => !state.solveOrder.includes(i))];

  order.forEach((catIndex) => {
    const cat = state.puzzle.categories[catIndex];
    const colorNum = state.solveOrder.includes(catIndex) ? state.solveOrder.indexOf(catIndex) + 1 : 0;

    const li = document.createElement("li");
    li.className = `legend-item${colorNum ? ` cat-${colorNum}` : " cat-unsolved"}`;

    const title = document.createElement("span");
    title.className = "cat-title";
    title.textContent = cat.title;

    const words = document.createElement("span");
    words.className = "cat-words";
    const all = [state.puzzle.pivot, ...cat.words];
    words.innerHTML = all
      .map((w) => (w === state.puzzle.pivot ? `<span class="pivot-word">${w.toUpperCase()}</span>` : w.toUpperCase()))
      .join(" · ");

    li.appendChild(title);
    li.appendChild(words);
    els.legendList.appendChild(li);
  });
}

loadPuzzle();