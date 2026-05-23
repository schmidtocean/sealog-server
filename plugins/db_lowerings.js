const {
  loweringsTable
} = require('../config/db_constants');

const { filePreProcessor } = require('../lib/utils');

exports.plugin = {
  name: 'db_populate_lowerings',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const resetDB = ['development', 'test'].includes(process.env.NODE_ENV);

    console.log('Searching for Lowerings Collection');
    const result = await db.listCollections({ name: loweringsTable }).toArray();

    if (result.length) {
      if (!resetDB) {
        console.log('Lowerings Collection already exists... we\'re done here.');
        return;
      }

      console.log('Lowerings Collection exists... dropping it!');
      try {
        await db.dropCollection(loweringsTable);
      }
      catch (err) {
        console.log('DROP ERROR:', err.code);
        throw (err);
      }
    }

    console.log('Creating Lowerings Collection');
    try {
      const collection = await db.createCollection(loweringsTable);

      if (resetDB) {
        console.log('Populating Lowerings Collection');
        const init_data = filePreProcessor('./demo/FKt230303_S0492_loweringRecord.json', 'lowerings');
        await collection.insertMany(init_data);
      }
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }
  }
};
