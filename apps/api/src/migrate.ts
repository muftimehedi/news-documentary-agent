import dotenv from 'dotenv';
import path from 'node:path';
dotenv.config({ path: path.resolve(process.cwd(), '../../.env') });
dotenv.config();
import { migrate } from './db.js';
migrate().then(({ dialect }) => { console.log(`migrated (${dialect})`); process.exit(0); })
  .catch((e) => { console.error(e); process.exit(1); });
