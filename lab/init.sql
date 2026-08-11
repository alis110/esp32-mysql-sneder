CREATE TABLE IF NOT EXISTS lab_events (
  id BIGINT NOT NULL AUTO_INCREMENT,
  temperature DECIMAL(10, 2) NOT NULL,
  note VARCHAR(100) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
);

INSERT INTO lab_events (temperature, note) VALUES
  (73.40, 'sample-1'),
  (74.10, 'sample-2'),
  (72.00, 'sample-3');
