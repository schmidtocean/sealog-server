const {
  usersTable
} = require('../config/db_constants');

const { filePreProcessor } = require('../lib/utils');

exports.plugin = {
  name: 'db_populate_users',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const resetDB = ['development', 'test'].includes(process.env.NODE_ENV);

    console.log('Searching for Users Collection');
    const result = await db.listCollections({ name: usersTable }).toArray();

    if (result.length) {
      if (!resetDB) {
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

    console.log('Creating Users Collection');
    try {
      const collection = await db.createCollection(usersTable);
      const init_data = await filePreProcessor('./init_data/system_users_soi.json', 'users');
      console.log('Populating Users Collection');
      await collection.insertMany(init_data);
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }
  }
};
