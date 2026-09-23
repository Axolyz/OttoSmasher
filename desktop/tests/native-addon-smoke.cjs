// Run with Electron in Node mode: catches host import/link errors before packing.
const path = require('node:path');
const addon = require(path.resolve(__dirname, '../../.runtime/player.node'));
const id = addon.create(Buffer.alloc(8), false);
try {
  addon.poll(id);
  console.log('Electron host imports and headless libmpv initialization passed');
} finally { addon.destroy(id); }
