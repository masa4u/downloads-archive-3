import fs from 'fs';
import util from 'util';
const fs_readdir = util.promisify(fs.readdir);

(async () => {
  const files = await fs_readdir('.');
  for (let fn of files) {
    console.log(fn);
  }
})().catch(err => { console.error(err); });