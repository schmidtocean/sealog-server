const Fs = require('fs');
const { randomAsciiString, hashedPassword } = require('../lib/utils');

const {
  usersTable
} = require('../config/db_constants');

const init_data_filepath = './init_data/system_users.json';

const default_passwd = process.env.SEALOG_DEFAULT_PASSWD || 'demo';

exports.plugin = {
  name: 'db_populate_users',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const ObjectID = server.mongo.ObjectID;

    console.log('Searching for Users Collection');
    const result = await db.listCollections({ name: usersTable }).toArray();

    if (result.length) {
      if (process.env.NODE_ENV === 'production') {
        console.log('Users Collection already exists... we\'re done here.');
        return;
      }

      console.log('Users Collection exists... dropping it!');
      try {
        await db.dropCollection(usersTable);
      }
      catch (err) {
        console.log('DROP ERROR:', err.code);
        throw (err);
      }
    }

    let collection = null;
    let modified_data = [];
    console.log('Creating Users Collection');
    try {
      collection = await db.createCollection(usersTable);
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }

    console.log('Populating Users Collection');
    try {
      const data = Fs.readFileSync(init_data_filepath, 'utf8');

      const init_data = JSON.parse(data);
      await init_data.forEach(async (user) => {
	user._id = ObjectID(user.id);
        delete user.id;

        user.loginToken = randomAsciiString(20);

        const passwd_str = (user.username === 'guest') ? '' : default_passwd;
        user.password = await hashedPassword(passwd_str);

        modified_data.push(user);
      });
    }
    catch (err) {
      console.error('READ ERROR event_templates.json file:', err.code);
      throw (err);
    }

    try {
      await collection.insertMany(modified_data);
    }
    catch (err) {
      console.error('INSERT ERROR:', err.code);
      throw (err);
    }
  }
};

