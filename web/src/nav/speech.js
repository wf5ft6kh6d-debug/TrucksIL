// Voice output over the Web Speech API (speechSynthesis). Which voices exist depends entirely on
// the device/OS/browser; when no voice matches the UI language we stay silent and say so in the
// UI rather than read Hebrew/Arabic with an English voice.

/** UI language -> BCP 47 tag used for Valhalla narrative and for voice selection. */
export const SPEECH_LANG = { he: 'he-IL', ru: 'ru-RU', ar: 'ar-SA', en: 'en-US' };

const norm = (s) => String(s || '').replace('_', '-').toLowerCase().replace(/^iw\b/, 'he');

/**
 * Best voice for a BCP 47 tag: exact match, then same primary language (ar-SA -> ar-EG),
 * preferring local (on-device) voices. null if none.
 */
export function pickVoice(voices, tag) {
  const want = norm(tag);
  const primary = want.split('-')[0];
  const list = Array.isArray(voices) ? voices : [];
  const score = (v) => {
    const l = norm(v.lang);
    if (l === want) return 3;
    if (l.split('-')[0] === primary) return 2;
    return 0;
  };
  let best = null;
  for (const v of list) {
    const s = score(v);
    if (!s) continue;
    const ss = s + (v.localService ? 0.5 : 0);
    if (!best || ss > best.s) best = { v, s: ss };
  }
  return best ? best.v : null;
}

/**
 * Speech queue. Utterances are spoken one at a time in order; priority 'high' (TrucksIL
 * warnings) jumps ahead of queued instructions, and stale queued items are dropped beyond maxQueue.
 * @param {object} o
 * @param {object|null} o.synth        window.speechSynthesis (or a mock)
 * @param {Function}    o.Utterance    SpeechSynthesisUtterance constructor (or a mock)
 */
export function createSpeechQueue({ synth, Utterance, maxQueue = 3 } = {}) {
  const queue = [];
  let speaking = false;
  let enabled = false;
  let tag = 'en-US';
  const supported = Boolean(synth && Utterance);

  const voiceStatus = () => {
    if (!supported) return 'unsupported';
    const voices = synth.getVoices ? synth.getVoices() : [];
    if (!voices.length) return 'unknown'; // list not loaded yet / browser does not expose voices
    return pickVoice(voices, tag) ? 'ok' : 'noVoice';
  };

  const next = () => {
    if (speaking || !queue.length || !enabled) return;
    const item = queue.shift();
    const voices = synth.getVoices ? synth.getVoices() : [];
    const voice = pickVoice(voices, tag);
    if (voices.length && !voice) { queue.length = 0; return; }
    const u = new Utterance(item.text);
    u.lang = tag;
    if (voice) u.voice = voice;
    speaking = true;
    const done = () => { speaking = false; next(); };
    u.onend = done;
    u.onerror = done;
    synth.speak(u);
  };

  return {
    supported,
    get enabled() { return enabled; },
    get lang() { return tag; },
    get pending() { return queue.length; },
    voiceStatus,
    setEnabled(on) { enabled = Boolean(on) && supported; if (!enabled) this.cancel(); },
    setLang(t) { tag = t; },
    /** @returns {boolean} queued */
    say(text, { priority = 'normal' } = {}) {
      if (!enabled || !text) return false;
      if (priority === 'high') queue.unshift({ text, priority }); else queue.push({ text, priority });
      while (queue.length > maxQueue) {
        const idx = queue.map((q) => q.priority).lastIndexOf('normal');
        queue.splice(idx >= 0 ? idx : queue.length - 1, 1);
      }
      next();
      return true;
    },
    cancel() { queue.length = 0; speaking = false; if (supported && synth.cancel) synth.cancel(); },
  };
}
