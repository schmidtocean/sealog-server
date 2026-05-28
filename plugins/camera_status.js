

const axios = require('axios');
const { cameraStatusUrls } = require('../config/server_settings');
const { customVarsTable } = require('../config/db_constants');

const POLL_INTERVAL_MS = 30000;

exports.plugin = {
  name: 'camera_status',
  dependencies: [],
  register: (server, options) => {

    const db = server.mongo.db;
    const cameras = Object.entries(cameraStatusUrls || {}).filter(([, url]) => url);

    if (cameras.length === 0) {
      return;
    }

    const checkCamera = async (key, url) => {
      const varName = `${key}RecState`;
      let value;

      try {
        const response = await axios.get(url, { timeout: 5000 });
        value = response.data.rec_state ? 'true' : 'false';
      }
      catch {
        value = 'unavailable';
      }

      try {
        const result = await db.collection(customVarsTable).findOneAndUpdate(
          { custom_var_name: varName },
          { $set: { custom_var_value: value } },
          { returnNewDocument: true }
        );

        if (result.value) {
          server.publish('/ws/status/updateCustomVars', {
            id: result.value._id,
            custom_var_name: varName,
            custom_var_value: value
          });
        }
      }
      catch (err) {
        server.log(['error', 'camera_status'], `DB update failed for ${varName}: ${err.message}`);
      }
    };

    const pollAll = () => Promise.all(cameras.map(([key, url]) => checkCamera(key, url)));

    setInterval(pollAll, POLL_INTERVAL_MS);
  }
};
