// The chat route streams SSE. Keep the text of the event that ends the turn (answer, refused, clarify or error),
// which is what the user sees; progress events are dropped.
module.exports = (json, text) => {
  let final = '';
  for (const block of String(text).split('\n\n')) {
    const type = (block.match(/^event: (.+)$/m) || [])[1];
    const data = (block.match(/^data: (.+)$/m) || [])[1];
    if (!type || !data || type === 'progress') continue;
    const payload = JSON.parse(data);
    if (['answer', 'refused', 'clarify', 'error'].includes(type)) final = `[${type}] ${payload.text}`;
  }
  return final || '[no final event]';
};
