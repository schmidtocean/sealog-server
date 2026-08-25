const Lab = require('@hapi/lab');
const { expect } = require('@hapi/code');

const { afterEach, describe, it } = exports.lab = Lab.script();

const Axios = require('axios');
const { cameraStatusUrls } = require('../config/server_settings');
const CameraStatus = require('../plugins/camera_status');

const originalAxiosGet = Axios.get;
const originalCameraStatusUrls = Object.assign({}, cameraStatusUrls);
const originalSetInterval = global.setInterval;

describe('Camera status plugin', () => {

  afterEach(() => {

    Axios.get = originalAxiosGet;
    Object.keys(cameraStatusUrls).forEach((key) => delete cameraStatusUrls[key]);
    Object.assign(cameraStatusUrls, originalCameraStatusUrls);
    global.setInterval = originalSetInterval;
  });

  it('publishes the updated custom variable returned by MongoDB 6', async () => {

    let databaseCall;
    let publishCall;
    let scheduledPoll;
    let scheduledInterval;

    cameraStatusUrls.scicam = 'http://camera.test/status';
    cameraStatusUrls.sitcam = null;
    Axios.get = () => Promise.resolve({ data: { rec_state: true } });
    global.setInterval = (poll, interval) => {

      scheduledPoll = poll;
      scheduledInterval = interval;
    };

    const server = {
      mongo: {
        db: {
          collection: (table) => ({
            findOneAndUpdate: (...args) => {

              databaseCall = { table, args };
              return Promise.resolve({ _id: 'camera-status-id' });
            }
          })
        }
      },
      publish: (...args) => {

        publishCall = args;
      },
      log: () => {}
    };

    CameraStatus.plugin.register(server, {});
    await scheduledPoll();

    expect(scheduledInterval).to.equal(30000);
    expect(databaseCall).to.equal({
      table: 'custom_vars',
      args: [
        { custom_var_name: 'scicamRecState' },
        { $set: { custom_var_value: 'true' } },
        { returnDocument: 'after' }
      ]
    });
    expect(publishCall).to.equal([
      '/ws/status/updateCustomVars',
      {
        id: 'camera-status-id',
        custom_var_name: 'scicamRecState',
        custom_var_value: 'true'
      }
    ]);
  });
});
