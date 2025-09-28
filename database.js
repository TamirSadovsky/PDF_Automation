require("dotenv").config();
const { Connection, Request, TYPES } = require("tedious");

const PHONE_NUMBER_ID = process.env.PHONE_NUMBER_ID;

const config = {
  server: process.env.DB_SERVER,
  authentication: {
    type: "default",
    options: {
      userName: process.env.DB_USER,
      password: process.env.DB_PASS,
    },
  },
  options: {
    database: process.env.DB_NAME,
    encrypt: true,
    trustServerCertificate: true,
    port: parseInt(process.env.DB_PORT),
    rowCollectionOnRequestCompletion: true,
  },
};

// שימוש ב־DB_NAME2 לקונפיג נפרד לטוקן
const dbConfig = {
  ...config,
  options: {
    ...config.options,
    database: process.env.DB_NAME2,
  },
};

function queryDatabase(query, params = {}) {
  return new Promise((resolve, reject) => {
    const connection = new Connection(config);

    connection.connect((err) => {
      if (err) {
        console.error("❌ Connection Failed", err);
        return reject(err);
      }

      const isExec = /^EXEC\s+/.test(query.trim());
      const request = new Request(query, (err, rowCount, rows) => {
        if (err) {
          console.error("❌ Query Error", err);
          return reject(err);
        }

        const result = rows.map((row) => {
          const obj = {};
          row.forEach((col) => {
            obj[col.metadata.colName] = col.value;
          });
          return obj;
        });

        resolve(result);
        connection.close();
      });

      Object.entries(params).forEach(([key, value]) => {
        request.addParameter(key, TYPES.NVarChar, value);
      });

      connection.execSql(request);
    });
  });
}

// מחזיר את הטוקן מ־DB_NAME2
function getLatestToken() {
  return new Promise((resolve, reject) => {
    const connection = new Connection(dbConfig);
    connection.connect((err) => {
      if (err) {
        console.error("❗ Failed to connect to DB:", err);
        return reject(err);
      }

      const request = new Request("EXEC Atidim.dbo.GetFBToken", (err, rowCount, rows) => {
        if (err) {
          console.error("❗ Failed to run query:", err);
          return reject(err);
        }

        const row = rows?.[0];
        const token = row?.find(col => col.metadata.colName === "WA_ACCESS_TOKEN")?.value || null;
        resolve(token);
        connection.close();
      });

      connection.execSql(request);
    });
  });
}

module.exports = { queryDatabase, getLatestToken, PHONE_NUMBER_ID };
