CREATE TABLE SENSOR_AM2302 (
    TIMESTAMP TIMESTAMP PRIMARY KEY DEFAULT NOW(),
    LOCATED VARCHAR(255),
    TEMPERATURE NUMERIC(5, 2),
    HUMIDITY NUMERIC(5, 2)
);

INSERT INTO SENSOR_AM2302 (located, temperature, humidity)
VALUES ('Teste', 24.50, 68.20);

 CREATE TABLE KWH_CONSUMPTION (
    reading_timestamp TIMESTAMP WITH TIME ZONE PRIMARY KEY DEFAULT NOW(),
    location VARCHAR(15) NOT NULL,
    accumulated NUMERIC(10, 2) NOT NULL,
    value NUMERIC(10, 2) NOT NULL
);

CREATE TABLE KEEPALIVE (
    timestamp TIMESTAMPTZ PRIMARY KEY,
    location VARCHAR(100),
    name VARCHAR(100)
);


--=============================
--Logando: psql -U csti -d c102
--Vendo tabelas:
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_type = 'BASE TABLE';