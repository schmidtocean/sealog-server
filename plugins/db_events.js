const {
  eventsTable
} = require('../config/db_constants');

const { filePreProcessor } = require('../lib/utils');

exports.plugin = {
  name: 'db_populate_events',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const resetDB = ['development', 'test'].includes(process.env.NODE_ENV);

    console.log('Searching for Events Collection');
    const result = await db.listCollections({ name: eventsTable }).toArray();

    if (result.length) {
      if (!resetDB) {
        console.log('Events Collection already exists... we\'re done here.');
        return;
      }

      console.log('Events Collection exists... dropping it!');
      try {
        await db.dropCollection(eventsTable);
      }
      catch (err) {
        console.log('DROP ERROR:', err.code);
        throw (err);
      }
    }

    console.log('Creating Events Collection');
    try {
      const collection = await db.createCollection(eventsTable);

      if (resetDB) {
        console.log('Populating Events Collection');
        let init_data = [];

        if (process.env.SEALOG_INSTANCE_TYPE === 'FKt') {
          init_data = filePreProcessor('./demo/FKt230303_eventOnlyExport.json', 'events');
        }
        else if (process.env.SEALOG_INSTANCE_TYPE === 'Sub') {
          init_data = filePreProcessor('./demo/FKt230303_S0492_eventOnlyExport.json', 'events');
        }
        else if (process.env.SEALOG_INSTANCE_TYPE === 'emp') {
          init_data = filePreProcessor('./demo/FKt260806_E0018_eventOnlyExport.json', 'events');
        }

        if (init_data.length > 0) {
          await collection.insertMany(init_data);
        }
      }
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }
  }
};
