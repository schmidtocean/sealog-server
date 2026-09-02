const {
  cruisesTable
} = require('../config/db_constants');

const { filePreProcessor } = require('../lib/utils');

exports.plugin = {
  name: 'db_populate_cruises',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const resetDB = ['development', 'test'].includes(process.env.NODE_ENV);

    console.log('Searching for Cruises Collection');
    const result = await db.listCollections({ name: cruisesTable }).toArray();

    if (result.length) {
      if (!resetDB) {
        console.log('Cruises Collection already exists... we\'re done here.');
        return;
      }

      console.log('Cruises Collection exists... dropping it!');
      try {
        await db.dropCollection(cruisesTable);
      }
      catch (err) {
        console.log('DROP ERROR:', err.code);
        throw (err);
      }
    }

    console.log('Creating Cruises Collection');
    try {
      const collection = await db.createCollection(cruisesTable);

      if (resetDB) {
        console.log('Populating Cruises Collection');

        let init_data = [];
        if (process.env.SEALOG_INSTANCE_TYPE === 'emp') {
          init_data = filePreProcessor('./demo/FKt260806_cruiseRecord.json', 'cruises');
        }
        else {
          init_data = filePreProcessor('./demo/FKt230303_cruiseRecord.json', 'cruises');
        }

        await collection.insertMany(init_data);
      }
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }
  }
};
