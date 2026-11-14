-- A schema of the kind coding agents actually emit: plausible, and quietly wrong.

CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  email TEXT,
  username TEXT,
  password TEXT,
  role TEXT DEFAULT 'user',
  bio TEXT,
  is_active TEXT DEFAULT 'true',
  created_at TEXT
);

CREATE TABLE posts (
  id SERIAL PRIMARY KEY,
  user_id INTEGER,
  title TEXT,
  slug TEXT,
  body TEXT,
  status TEXT DEFAULT 'draft',
  view_count TEXT DEFAULT '0',
  published_at TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE comments (
  id SERIAL PRIMARY KEY,
  post_id INTEGER REFERENCES posts(id),
  user_id INTEGER REFERENCES users(id),
  parent_id INTEGER,
  body TEXT,
  approved TEXT DEFAULT 'false',
  created_at TEXT
);

CREATE TABLE tags (
  id SERIAL PRIMARY KEY,
  name TEXT,
  slug TEXT
);

CREATE TABLE post_tags (
  id SERIAL PRIMARY KEY,
  post_id INTEGER REFERENCES posts(id),
  tag_id INTEGER REFERENCES tags(id)
);

CREATE TABLE media (
  id SERIAL PRIMARY KEY,
  post_id INTEGER,
  url TEXT,
  alt_text TEXT,
  metadata TEXT,
  uploaded_by INTEGER,
  created_at TEXT
);

CREATE TABLE settings (
  key TEXT,
  value TEXT
);
