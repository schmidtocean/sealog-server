const Lab = require('@hapi/lab');
const { expect } = require('@hapi/code');

const { afterEach, beforeEach, describe, it } = exports.lab = Lab.script();

const configPath = require.resolve('../config/server_settings.js.dist');
const booleanEnvVars = [
  'SEALOG_DISABLE_SELF_REGISTRATION',
  'SEALOG_SERVER_USE_ACCESS_CONTROL'
];
const originalEnv = {};

describe('Server settings', () => {

  beforeEach(() => {

    booleanEnvVars.forEach((name) => {

      originalEnv[name] = process.env[name];
      delete process.env[name];
    });
    delete require.cache[configPath];
  });

  afterEach(() => {

    booleanEnvVars.forEach((name) => {

      if (originalEnv[name] === undefined) {
        delete process.env[name];
      }
      else {
        process.env[name] = originalEnv[name];
      }
    });
    delete require.cache[configPath];
  });

  it('defaults boolean settings to false', () => {

    const settings = require(configPath);

    expect(settings.disableRegisteringUsers).to.be.false();
    expect(settings.useAccessControl).to.be.false();
  });

  it('parses the string false as false', () => {

    process.env.SEALOG_DISABLE_SELF_REGISTRATION = 'false';
    process.env.SEALOG_SERVER_USE_ACCESS_CONTROL = 'false';

    const settings = require(configPath);

    expect(settings.disableRegisteringUsers).to.be.false();
    expect(settings.useAccessControl).to.be.false();
  });

  it('parses the string true as true', () => {

    process.env.SEALOG_DISABLE_SELF_REGISTRATION = 'true';
    process.env.SEALOG_SERVER_USE_ACCESS_CONTROL = 'true';

    const settings = require(configPath);

    expect(settings.disableRegisteringUsers).to.be.true();
    expect(settings.useAccessControl).to.be.true();
  });
});
